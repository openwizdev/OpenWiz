//! Q1: the actual CLI executor with recording GitHub and room-cli sources.
use super::*;
use openwiz_adapter_github::{process::Executor, tick::TickReads};
use openwiz_cli::fleet::tick::{self as cli, Args, Context, Control};
use serde_json::{Value, json};
use std::sync::{Arc, Mutex, atomic::AtomicBool};
struct World {
    fixture: Fixture,
    calls: Arc<Mutex<Vec<Vec<String>>>>,
    stop: Arc<AtomicBool>,
    comments: Arc<Mutex<std::collections::BTreeMap<u64, Vec<Value>>>>,
}
fn rules() -> String {
    let mut s = String::new();
    for (section, provider) in [
        ("Builder", "codex"),
        ("Builder for small tickets", "codex"),
        ("Reviewer for Claude-built", "codex"),
        ("Reviewer for GPT-built", "claude-code"),
    ] {
        s += &format!(
            "## {section}\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Synthetic | `--provider {provider}` |\n| Model | Synthetic | `--model syn-model` |\n| Effort | High | `--reasoning-level high` |\n"
        );
    }
    s + "## CI checks\n| Check | Runs | Required on |\n| --- | --- | --- |\n| `rust` | tests | `main` |\n## Standing merge rules\n| Pull request | Review | Merged by, and when |\n| --- | --- | --- |\n| A ticket in an approved plan graph | reviewer | The loop, as soon as the reviewer's APPROVE names that exact commit |\n"
}
fn links(ns: &[u64]) -> Value {
    json!({"nodes":ns.iter().map(|n|json!({"id":format!("syn-{n}"),"number":n,"state":"CLOSED","title":"Synthetic","url":format!("https://example.invalid/issues/{n}")})).collect::<Vec<_>>(),"totalCount":ns.len()})
}
impl World {
    fn new() -> Self {
        let f = Fixture::new();
        place_script(
            &f.0.join("room"),
            r#"#!/usr/bin/python3
import json,pathlib,sys
r=pathlib.Path(__file__).parent
a=sys.argv[1:]
with (r/'room-calls').open('a') as f:f.write(json.dumps(a)+'\n')
if a==['--version']:print('v127')
elif a[:2]==['project','list']:
    p=r/'project-reads';n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n))
    project='prj_syn_other' if (r/'foreign').exists() or ((r/'flip').exists() and n>=2) else 'prj_syn_1'
    print(json.dumps([{'id':project,'kind':'standard','name':'Synthetic','gitRemoteUrl':'https://github.com/synthetic-owner/synthetic-repo','createdAt':1700000000000,'updatedAt':1700000000000,'sources':[]}]))
elif a[:2]==['thread','show']:print(json.dumps({'thread':{'id':a[2],'projectId':'prj_syn_foreign' if (r/'foreign-thread').exists() else 'prj_syn_1','archivedAt':None if (r/'foreign-thread').exists() else 1700000000000}}))
elif a[:2]==['thread','list']:print((r/'threads.json').read_text())
elif a==['loop','list','--json']:print((r/'loops.json').read_text())
elif a==['loop','pause','loop_syn_1','--json']:print('{}')
else:sys.exit(2)
"#,
        );
        let template: Value = serde_json::from_str(include_str!(
            "../fixtures/room-cli-v127/new-thread/thread-show-active.json"
        ))
        .unwrap();
        let rows = [10, 11, 12].map(|n| {
            let mut row = template["thread"].clone();
            row["id"] = json!(format!("thr_syn_{n}"));
            row["projectId"] = json!("prj_syn_1");
            row["title"] = json!(format!("#{n}: Synthetic"));
            row["archivedAt"] = json!(1700000000000u64);
            row
        });
        fs::write(f.0.join("threads.json"), json!(rows).to_string()).unwrap();
        let comments=std::collections::BTreeMap::from([10,11].map(|n|(n,vec![json!({"id":n*10,"body":"launch-fleet: started","created":1700000000000u64,"updated":1700000000000u64})])));
        Self {
            fixture: f,
            calls: Arc::new(Mutex::new(Vec::new())),
            stop: Arc::new(AtomicBool::new(false)),
            comments: Arc::new(Mutex::new(comments)),
        }
    }
    fn github(&self, stop_after_record: bool) -> TickReads {
        let calls = self.calls.clone();
        let comments = self.comments.clone();
        let stop = self.stop.clone();
        let root = self.fixture.0.clone();
        TickReads::with_executor(Executor::supplied(Arc::new(move |call, _| {
            let args = call
                .argv()
                .iter()
                .map(|s| s.to_string())
                .collect::<Vec<_>>();
            calls.lock().unwrap().push(args.clone());
            let words = args.iter().map(String::as_str).collect::<Vec<_>>();
            let mut cs = comments.lock().unwrap();
            let answer = match &words[..] {
                ["repo", "view", "--json", "nameWithOwner,isPrivate"] => {
                    json!({"nameWithOwner":"synthetic-owner/synthetic-repo","isPrivate":true})
                }
                ["repo", "view", ..] => {
                    json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic-owner/synthetic-repo","url":"https://github.invalid/synthetic-owner/synthetic-repo"})
                }
                ["issue", "list", ..] => {
                    if root.join("ready-fleet").exists() {
                        return Ok(json!([9,10,11].map(|n|{
                            let mut subs=links(if n==9 {&[10,11]}else{&[]});
                            for node in subs["nodes"].as_array_mut().unwrap(){node["state"]=json!("OPEN");}
                            let mut blocked=links(if n==11 {&[10]}else{&[]});
                            for node in blocked["nodes"].as_array_mut().unwrap(){node["state"]=json!("OPEN");}
                            json!({"blockedBy":blocked,"body":match n {9=>"Synthetic graph",10=>"**Owned paths:** `crates/example/one.rs`\n**Relies on:** nothing",_=>"**Owned paths:** `crates/example/two.rs`\n**Relies on:** nothing"},"id":format!("syn-{n}"),"labels":if n==9 {vec![]}else{vec![json!({"id":"syn-label-ready-for-agent","name":"ready-for-agent","description":"Synthetic","color":"ffffff"})]},"milestone":null,"number":n,"state":"OPEN","subIssues":subs,"title":if n==9 {"Synthetic graph".into()}else{format!("Synthetic ticket {n}")}})
                        })).to_string().into_bytes());
                    }
                    let multi = root.join("multi-fleet").exists();
                    let numbers = if multi {
                        vec![9, 10, 11, 19, 12]
                    } else {
                        vec![9, 10, 11]
                    };
                    json!(numbers.into_iter().map(|n|json!({"blockedBy":links(&[]),"body":"**Owned paths:** `crates/example.rs`\n**Relies on:** nothing","id":format!("syn-{n}"),"labels":[],"milestone":null,"number":n,"state":"CLOSED","subIssues":links(if n==9 {&[10,11]} else if n==19 && multi {&[12]}else{&[]}),"title":"Synthetic"})).collect::<Vec<_>>())
                }
                ["pr", "list", ..] => json!([]),
                ["api", path, ..] => {
                    let path = path.strip_prefix("repos/{owner}/{repo}/").unwrap();
                    if path.starts_with("git/ref/heads/") {
                        json!({"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
                    } else if path.starts_with("contents/docs/agents/fleet.md") {
                        return Ok(rules().into_bytes());
                    } else if path.starts_with("issues/comments?") {
                        json!(cs.iter().flat_map(|(n,rows)|rows.iter().map(move |c|{let mut c=c.clone();c["issue_url"]=json!(format!("https://github.invalid/api/v3/repos/synthetic-owner/synthetic-repo/issues/{n}"));c})).collect::<Vec<_>>())
                    } else if path.starts_with("issues/") && path.contains("/comments?") {
                        let n = path.split('/').nth(1).unwrap().parse::<u64>().unwrap();
                        json!(cs.get(&n).cloned().unwrap_or_default())
                    } else {
                        return Err(openwiz_core::source::SourceError::Unavailable {
                            detail: "unexpected synthetic API read".into(),
                        });
                    }
                }
                ["issue", "comment", n, "--body", body] => {
                    let n = n.parse::<u64>().unwrap();
                    cs.entry(n).or_default().push(json!({"id":1000+n,"body":body,"created":1700000001000u64,"updated":1700000001000u64}));
                    if stop_after_record {
                        stop.store(true, Ordering::SeqCst);
                    }
                    return Ok(format!("https://github.invalid/synthetic-owner/synthetic-repo/issues/{n}#issuecomment-{}\n",1000+n).into_bytes());
                }
                ["issue", "view", n, "--json", "comments"] => {
                    let n = n.parse::<u64>().unwrap();
                    json!({"comments":cs.get(&n).unwrap().iter().map(|c|json!({"id":format!("syn-{}",c["id"]),"author":null,"authorAssociation":"OWNER","body":c["body"],"createdAt":"2023-11-14T22:13:20Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":null,"reactionGroups":[],"url":format!("https://github.invalid/synthetic-owner/synthetic-repo/issues/{n}#issuecomment-{}",c["id"]),"viewerDidAuthor":true})).collect::<Vec<_>>()})
                }
                _ => {
                    return Err(openwiz_core::source::SourceError::Unavailable {
                        detail: "unexpected synthetic call".into(),
                    });
                }
            };
            Ok(answer.to_string().into_bytes())
        })))
    }
    fn run(&self, stop_after_record: bool, controlled: bool) -> Result<Value, &'static str> {
        let gh = self.github(stop_after_record);
        let room = self.fixture.source();
        let mut out = Vec::new();
        let args = Args {
            due: false,
            dry_run: false,
            json: true,
        };
        let context = Context {
            github: &gh,
            room: &room,
            state: &self.fixture.0,
            orchestrator: None,
        };
        if controlled {
            cli::run_with_control(
                args,
                context,
                &mut out,
                &Control::new("prj_syn_1", self.stop.clone()).unwrap(),
            )?;
        } else {
            cli::run_with(args, context, &mut out)?;
        }
        Ok(serde_json::from_slice(&out).unwrap())
    }
    fn writes(&self) -> Vec<Vec<String>> {
        self.calls
            .lock()
            .unwrap()
            .iter()
            .filter(|a| a.get(1).is_some_and(|s| s == "comment"))
            .cloned()
            .collect()
    }
}

fn multi_fleet(w: &World) {
    fs::write(w.fixture.0.join("multi-fleet"), "").unwrap();
    w.comments.lock().unwrap().insert(12,vec![json!({"id":120,"body":"launch-fleet: started","created":1700000000000u64,"updated":1700000000000u64})]);
}
fn tick_sources(w: &World) -> openwiz_service::tick::Sources {
    openwiz_service::tick::Sources {
        github: w.github(false).executor().clone(),
        room: w.fixture.source(),
    }
}
fn config(w: &World) -> Value {
    serde_json::from_slice(&fs::read(w.fixture.0.join("service/config.json")).unwrap()).unwrap()
}
#[test]
fn r1_failed_pause_fences_scheduled_dispatch_and_reload_but_other_fleets_continue() {
    use openwiz_core::health::model::*;
    use openwiz_service::{
        health::{Health, RuntimeFixes},
        scheduler::Scheduler,
        state::State,
        tick,
    };
    struct NoRepair;
    impl RuntimeFixes for NoRepair {
        fn restart_tick(&self, _: Instant) -> Result<(), String> {
            panic!("unconfirmed pause must not replace")
        }
        fn restart_server(&self, _: Instant) -> Result<(), String> {
            panic!("no server fix")
        }
    }
    let w = World::new();
    multi_fleet(&w);
    let state = super::restart::state(&w.fixture);
    let mut rows: Value =
        serde_json::from_slice(&fs::read(w.fixture.0.join("loops.json")).unwrap()).unwrap();
    rows[0]["paused"] = json!(false);
    fs::write(w.fixture.0.join("loops.json"), rows.to_string()).unwrap();

    // The spec is open when health verifies takeover, then closes before
    // periodic cleanup. Even cleanup writes must respect the saved fence.
    let base = w.github(false).executor().clone();
    let health_github = Executor::supplied(Arc::new(move |call, until| {
        let out = base.run(call, until)?;
        if call.argv().get(1).is_some_and(|a| a == "list")
            && call.argv().first().is_some_and(|a| a == "issue")
        {
            let mut rows: Value = serde_json::from_slice(&out).unwrap();
            for row in rows.as_array_mut().unwrap() {
                if row["number"] == 9 {
                    row["state"] = json!("OPEN");
                }
            }
            Ok(rows.to_string().into_bytes())
        } else if call
            .argv()
            .get(1)
            .is_some_and(|a| a.contains("issues/9/comments?"))
        {
            let mut rows: Value = serde_json::from_slice(&out).unwrap();
            rows.as_array_mut().unwrap().insert(0,json!({"id":90,"body":"launch-fleet: fleet thread thr_syn_dead, loop loop_syn_1","created":1000,"updated":1000}));
            Ok(rows.to_string().into_bytes())
        } else {
            Ok(out)
        }
    }));
    let health = Health::new(
        &w.fixture.0,
        config(&w),
        state.clone(),
        w.fixture.source(),
        health_github,
        Arc::new(NoRepair),
    )
    .unwrap();
    health
        .pass(
            &Seen {
                cloudroom: CloudRoomSeen::Running,
                loops: Listed::Read(w.fixture.source().health_loops(deadline()).unwrap()),
                tick_running_since: None,
                fleet_threads: Listed::Read(vec![SeenFleetThread {
                    spec: Number::new(9).unwrap(),
                    thread: Id::parse("thr_syn_dead").unwrap(),
                    seen: ThreadSeen::Archived,
                }]),
                server: Known::Healthy,
            },
            4000,
        )
        .unwrap();
    assert_eq!(
        state.lock().unwrap().snapshot()["retired_loops"][0]["phase"],
        "pause_pending"
    );
    let before = w.writes().len();
    let mut jobs = Scheduler::default();
    tick::register_with_sources(
        &w.fixture.0,
        &config(&w),
        state,
        &mut jobs,
        tick_sources(&w),
        || 5000,
    )
    .unwrap();
    for at in [2, 4] {
        jobs.poll(at).unwrap();
        jobs.wait(tick::JOB).unwrap();
    }
    let resumed = Arc::new(Mutex::new(State::load(&w.fixture.0, 6000).unwrap()));
    let mut next = Scheduler::default();
    tick::register_with_sources(
        &w.fixture.0,
        &config(&w),
        resumed,
        &mut next,
        tick_sources(&w),
        || 6000,
    )
    .unwrap();
    next.poll(2).unwrap();
    next.wait(tick::JOB).unwrap();
    assert_eq!(
        w.writes()[before..]
            .iter()
            .map(|a| a[2].as_str())
            .collect::<Vec<_>>(),
        ["12"]
    );
}

#[test]
fn r1_a_running_tick_rechecks_authority_before_its_next_action() {
    use openwiz_service::{scheduler::Scheduler, tick};
    let w = World::new();
    multi_fleet(&w);
    let state = super::restart::state(&w.fixture);
    let base = w.github(false).executor().clone();
    let shared = state.clone();
    let github = Executor::supplied(Arc::new(move |call, until| {
        let answer = base.run(call, until)?;
        if call.argv().get(1).is_some_and(|a| a == "comment")
            && call.argv().get(2).is_some_and(|a| a == "10")
        {
            let mut state = shared.lock().unwrap();
            let mut value = state.snapshot().clone();
            value["retired_loops"] = json!([{"owner":"service_tick","spec":9,"thread":"thr_syn_dead","loop":"loop_syn_1","phase":"pause_pending","at":2000}]);
            state.save(value).unwrap();
        }
        Ok(answer)
    }));
    let mut jobs = Scheduler::default();
    tick::register_with_sources(
        &w.fixture.0,
        &config(&w),
        state,
        &mut jobs,
        tick::Sources {
            github,
            room: w.fixture.source(),
        },
        || 2000,
    )
    .unwrap();
    jobs.poll(2).unwrap();
    jobs.wait(tick::JOB).unwrap();
    assert_eq!(
        w.writes().iter().map(|a| a[2].as_str()).collect::<Vec<_>>(),
        ["10", "12"]
    );
}
#[test]
fn stopped_control_reads_or_dispatches_nothing() {
    let w = World::new();
    w.stop.store(true, Ordering::SeqCst);
    assert_eq!(w.run(false, true).unwrap_err(), "tick stop requested");
    assert!(w.calls.lock().unwrap().is_empty());
    assert!(!w.fixture.0.join("room-calls").exists());
}
#[test]
fn stop_after_an_action_preserves_its_readback_and_refuses_the_next_action() {
    let w = World::new();
    assert_eq!(w.run(true, true).unwrap_err(), "tick stop requested");
    assert_eq!(
        w.writes(),
        vec![
            vec!["issue", "comment", "10", "--body", "launch-fleet: archived"]
                .into_iter()
                .map(str::to_owned)
                .collect::<Vec<_>>()
        ]
    );
    assert!(
        w.calls
            .lock()
            .unwrap()
            .iter()
            .any(|a| a == &vec!["issue", "view", "10", "--json", "comments"])
    );
}
#[test]
fn controlled_tick_refuses_an_initial_foreign_project() {
    let w = World::new();
    fs::write(w.fixture.0.join("foreign"), "").unwrap();
    assert_eq!(
        w.run(false, true).unwrap_err(),
        "configured project changed or unread"
    );
    assert!(w.writes().is_empty());
}
#[test]
fn project_mapping_is_refreshed_before_dispatch() {
    let w = World::new();
    fs::write(w.fixture.0.join("flip"), "").unwrap();
    let doc = w.run(false, true).unwrap();
    assert_eq!(doc["actions"].as_array().unwrap().len(), 2, "{doc}");
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["outcome"]["state"] == "refused")
    );
    assert!(w.writes().is_empty());
}
#[test]
fn ordinary_cli_keeps_both_actions_and_their_records() {
    let w = World::new();
    let doc = w.run(false, false).unwrap();
    assert_eq!(w.writes().len(), 2, "{doc}");
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["outcome"]["state"] == "done"),
        "{doc}"
    );
}

#[test]
fn controlled_tick_never_attempts_to_archive_a_foreign_project_thread() {
    let w = World::new();
    fs::write(w.fixture.0.join("foreign-thread"), "").unwrap();
    let _ = w.run(false, true).unwrap();
    let calls = fs::read_to_string(w.fixture.0.join("room-calls"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    assert!(
        !calls.iter().any(|a| a[0] == "thread" && a[1] == "archive"),
        "{calls:?}"
    );
    assert!(w.writes().is_empty());
}

// synthetic_assumptions: an approved graph and a crash before create dispatch.
#[test]
fn r1_pending_recovery_obeys_the_same_fleet_fence() {
    use openwiz_core::{
        fleet::{
            model::Number,
            starts::{Attempt, AttemptOutcome, Repository, StartKey, StartRecord, StartStore},
        },
        messaging::OpId,
        model::Timestamp,
        new_thread::Settings,
    };
    const APPROVAL: &str = "**Plan graph approved by Jake, 2026-10-30, revision 1:** \"approved\"\n\n| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n| #10 | Synthetic ticket 10 | none | ready-for-agent |\n| #11 | Synthetic ticket 11 | #10 | ready-for-agent |\n\nFingerprint: `5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c`\n\n```text\nplan-graph revision v2\nspec #9 body sha256 e8ed494ca2bac1d6fd37b4742dcf45b43ac1180e687098745590f3692f90a71a\nticket #10 blocked-by none body sha256 60c009f9e72945c1dc45fe9f9bd9cd09dc092b5f87fcb23e3c873cf4372dca9e title Synthetic ticket 10\nticket #11 blocked-by #10 body sha256 04673879b8ae2d96eec6d0e9cc48f8fe4b3d735792fc246107f6661b40de4f3e title Synthetic ticket 11\n```\n";
    for fenced in [false, true] {
        let w = World::new();
        fs::write(w.fixture.0.join("ready-fleet"), "").unwrap();
        *w.comments.lock().unwrap() = std::collections::BTreeMap::from([(
            9,
            vec![
                json!({"id":100,"body":APPROVAL.replacen("\"approved\"\n", "approved as proposed.\nPrivate record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001\n",1),"created":1793400000000u64,"updated":1793400000000u64}),
            ],
        )]);
        let key = StartKey::builder(
            Repository::parse("synthetic-owner/synthetic-repo").unwrap(),
            Number::new(10).unwrap(),
        );
        let record = StartRecord::from_parts(
            key.id(),
            key.clone(),
            "prj_syn_1".into(),
            Settings {
                harness: "codex".into(),
                model: "syn-model".into(),
                effort: "high".into(),
            },
            vec![Attempt {
                op_id: OpId::parse("syn-r1-pending").unwrap(),
                at: Timestamp(1793400000000),
                outcome: AttemptOutcome::Pending,
            }],
        )
        .unwrap();
        let store = openwiz_store::StartFileStore::open(&w.fixture.0).unwrap();
        store.lock(&key).unwrap();
        store.write(&record).unwrap();
        store.unlock(&key);
        let gh = w.github(false);
        let room = w.fixture.source();
        let mut out = Vec::new();
        cli::run_with_control(
            Args {
                due: false,
                dry_run: false,
                json: true,
            },
            Context {
                github: &gh,
                room: &room,
                state: &w.fixture.0,
                orchestrator: None,
            },
            &mut out,
            &Control::new("prj_syn_1", w.stop.clone())
                .unwrap()
                .with_fleet_authority(move |spec| !fenced || spec.get() != 9),
        )
        .unwrap();
        let doc: Value = serde_json::from_slice(&out).unwrap();
        let saved = store.inspect(&key).unwrap().unwrap();
        if fenced {
            assert!(
                matches!(
                    saved.attempts().last().unwrap().outcome,
                    AttemptOutcome::Pending
                ),
                "{doc}"
            );
            assert!(w.writes().is_empty(), "{doc}");
        } else {
            assert!(
                !matches!(
                    saved.attempts().last().unwrap().outcome,
                    AttemptOutcome::Pending
                ),
                "unfenced baseline must actually dispatch recovery: {doc}"
            );
            assert_eq!(
                w.writes().len(),
                1,
                "recovery records its refused synthetic create: {doc}"
            );
        }
    }
}
