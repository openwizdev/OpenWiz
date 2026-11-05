//! Runtime-owner dispatch, actual scheduler and loopback server, no live tool.
use super::*;
use openwiz_service::{health::runtime::channel, scheduler::Scheduler, tick};
use std::{net::TcpListener, num::NonZeroU64, sync::Arc, thread};

fn stale_repair_case(successor: bool) {
    use openwiz_service::health::runtime::channel_with_monitor;
    use std::sync::mpsc;
    let f = Fixture::new();
    let state = super::restart::state(&f);
    let count = Arc::new(AtomicU64::new(0));
    let count_worker = count.clone();
    let release = Arc::new(AtomicU64::new(0));
    let release_worker = release.clone();
    let (entered, started) = mpsc::channel();
    let mut jobs = Scheduler::default();
    tick::register_with_control(
        &mut jobs,
        NonZeroU64::new(2).unwrap(),
        state,
        || 2000,
        move |stop| {
            let n = count_worker.fetch_add(1, Ordering::SeqCst);
            entered.send((n, stop.clone())).unwrap();
            let until = Instant::now() + RUN_BUDGET;
            while (n == 0 || successor && n == 1)
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
    assert_eq!(started.recv_timeout(RUN_BUDGET).unwrap().0, 0);
    let monitor = jobs.tick_monitor();
    let expected = monitor.current().unwrap().unwrap();
    let (control, requests) = channel_with_monitor(monitor.clone());
    let waiting = thread::spawn(move || control.restart_stalled_tick(expected, deadline()));
    let request = requests.recv_timeout(RUN_BUDGET).unwrap();
    release.store(1, Ordering::SeqCst);
    jobs.wait(tick::JOB).unwrap();
    let successor_flag = if successor {
        jobs.poll(4).unwrap();
        let (n, flag) = started.recv_timeout(RUN_BUDGET).unwrap();
        assert_eq!(n, 1);
        let current = monitor.current().unwrap().unwrap();
        assert_ne!(current.generation, expected.generation);
        assert_eq!(current.started_at, expected.started_at);
        Some(flag)
    } else {
        None
    };
    let mut server = super::server::server(Arc::new(|_| {}));
    assert!(!request.apply(&mut jobs, &mut server, || panic!(
        "tick repair cannot replace HTTP"
    )));
    let outcome = waiting.join().unwrap();
    let stopped = successor_flag
        .as_ref()
        .is_some_and(|flag| flag.load(Ordering::SeqCst));
    release.store(3, Ordering::SeqCst);
    jobs.wait(tick::JOB).unwrap();
    server.shutdown(deadline()).unwrap();
    server.join();
    assert!(
        !stopped,
        "stale repair set the healthy successor's stop flag"
    );
    assert_eq!(count.load(Ordering::SeqCst), if successor { 2 } else { 1 });
    assert!(outcome.is_err(), "changed/completed generation is refused");
}
#[test]
fn r2_completed_observation_cannot_restart_a_finished_run() {
    stale_repair_case(false);
}
#[test]
fn r2_stale_request_cannot_stop_a_successor_with_the_same_timestamp() {
    stale_repair_case(true);
}
#[test]
fn runtime_owner_restarts_its_tick_through_the_registered_control() {
    let f = Fixture::new();
    let state = super::restart::state(&f);
    let calls = Arc::new(AtomicU64::new(0));
    let count = calls.clone();
    let mut jobs = Scheduler::default();
    tick::register_with_control(
        &mut jobs,
        NonZeroU64::new(2).unwrap(),
        state,
        || 2000,
        move |_| {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    )
    .unwrap();
    jobs.poll(2).unwrap();
    jobs.wait(tick::JOB).unwrap();
    let mut server = super::server::server(Arc::new(|_| {}));
    let (control, requests) = channel();
    let request = thread::spawn(move || control.restart_tick(deadline()));
    let message = requests.recv_timeout(RUN_BUDGET).unwrap();
    assert!(!message.apply(&mut jobs, &mut server, || panic!(
        "tick repair must not replace HTTP"
    )));
    assert!(request.join().unwrap().is_ok());
    jobs.wait(tick::JOB).unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    server.shutdown(deadline()).unwrap();
    server.join();
}
#[test]
fn runtime_owner_stops_http_before_rebinding_the_same_port() {
    let mut server = super::server::server(Arc::new(|_| {}));
    let addr = server.local_addr();
    let (control, requests) = channel();
    let request = thread::spawn(move || control.restart_server(deadline()));
    let mut jobs = Scheduler::default();
    assert!(
        requests
            .recv_timeout(RUN_BUDGET)
            .unwrap()
            .apply(&mut jobs, &mut server, || {
                let listener = TcpListener::bind(addr)
                    .map_err(|_| "old listener is still active".to_owned())?;
                openwiz_server::start(
                    listener,
                    openwiz_server::Config::default(),
                    Arc::new(CloudRoomSource::new("/synthetic/unreachable-room")),
                    Arc::new(openwiz_server::SystemClock),
                    Arc::new(|_| {}),
                )
                .map_err(|_| "fixture start failed".into())
            })
    );
    assert!(request.join().unwrap().is_ok());
    assert_eq!(server.local_addr(), addr);
    assert!(super::server::health(addr).starts_with("HTTP/1.1 200"));
    server.shutdown(deadline()).unwrap();
    server.join();
}
#[test]
fn expired_runtime_request_cannot_make_a_late_effect() {
    let mut server = super::server::server(Arc::new(|_| {}));
    let addr = server.local_addr();
    let (control, requests) = channel();
    let mut jobs = Scheduler::default();
    let request = thread::spawn(move || control.restart_server(Instant::now()));
    assert!(request.join().unwrap().is_err());
    assert!(
        !requests
            .recv_timeout(RUN_BUDGET)
            .unwrap()
            .apply(&mut jobs, &mut server, || panic!(
                "expired request must not replace HTTP"
            ))
    );
    assert!(super::server::health(addr).starts_with("HTTP/1.1 200"));
    server.shutdown(deadline()).unwrap();
    server.join();
}

#[test]
fn service_process() {
    let Some(root) = std::env::var_os("OPENWIZ_T5_PROCESS_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    let mut jobs = Scheduler::default();
    let marker = root.join("other-job");
    jobs.register("synthetic-other", NonZeroU64::new(1).unwrap(), move || {
        fs::write(&marker, "ran").unwrap()
    })
    .unwrap();
    openwiz_service::runtime::run_with_health_sources(
        &root,
        &root.join("web"),
        &"a".repeat(40),
        jobs,
        |_| TcpListener::bind(("127.0.0.1", 0)),
        openwiz_service::health::Sources {
            room: CloudRoomSource::new(root.join("room")),
            github: openwiz_adapter_github::process::Executor::program(root.join("gh")),
        },
    )
    .unwrap();
}
// TA2 child stderr BEGIN
/// Drain continuously while retaining only a 2 KiB synthetic stderr prefix.
struct CapturedStderr {
    stop: Arc<std::sync::atomic::AtomicBool>,
    bytes: Arc<std::sync::Mutex<(Vec<u8>, bool)>>,
    reader: Option<thread::JoinHandle<()>>,
}
impl CapturedStderr {
    fn new() -> (Self, std::process::Stdio) {
        use std::io::Read;
        let (mut input, output) = std::os::unix::net::UnixStream::pair().unwrap();
        input
            .set_read_timeout(Some(Duration::from_millis(20)))
            .unwrap();
        let stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let bytes = Arc::new(std::sync::Mutex::new((Vec::new(), false)));
        let reader_stop = stop.clone();
        let reader_bytes = bytes.clone();
        let reader = thread::spawn(move || {
            let mut chunk = [0; 1024];
            loop {
                match input.read(&mut chunk) {
                    Ok(0) => break,
                    Ok(n) => {
                        let mut saved = reader_bytes.lock().unwrap_or_else(|e| e.into_inner());
                        let keep = n.min(2048_usize.saturating_sub(saved.0.len()));
                        saved.0.extend_from_slice(&chunk[..keep]);
                        saved.1 |= keep < n;
                    }
                    Err(e)
                        if matches!(
                            e.kind(),
                            std::io::ErrorKind::WouldBlock
                                | std::io::ErrorKind::TimedOut
                                | std::io::ErrorKind::Interrupted
                        ) => {}
                    Err(_) => break,
                }
                if reader_stop.load(Ordering::SeqCst) {
                    break;
                }
            }
        });
        let fd: std::os::fd::OwnedFd = output.into();
        (
            Self {
                stop,
                bytes,
                reader: Some(reader),
            },
            std::process::Stdio::from(fd),
        )
    }
}
impl CapturedStderr {
    fn finish(&mut self) {
        use std::io::Write;
        if self.reader.is_none() {
            return;
        }
        self.stop.store(true, Ordering::SeqCst);
        let drain_ok = self
            .reader
            .take()
            .is_none_or(|reader| reader.join().is_ok());
        if std::thread::panicking() {
            let saved = self.bytes.lock().unwrap_or_else(|e| e.into_inner());
            let report = format!(
                "[TA2 service-ci-diagnostics child-stderr] drain_ok={drain_ok} truncated={} {:?}\n",
                saved.1,
                String::from_utf8_lossy(&saved.0)
            );
            let _ = std::io::stderr().lock().write_all(report.as_bytes());
        }
    }
}
impl Drop for CapturedStderr {
    fn drop(&mut self) {
        self.finish();
    }
}
// TA2 child stderr END

struct Process(std::process::Child, CapturedStderr);
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
        self.1.finish();
    }
}
#[test]
fn actual_service_registers_health_without_replacing_tick_update_or_other_jobs() {
    let f = Fixture::new();
    let _state = super::restart::state(&f);
    DirBuilder::new()
        .mode(0o700)
        .create(f.0.join("web"))
        .unwrap();
    fs::write(f.0.join("web/index.html"), "synthetic page").unwrap();
    let path = f.0.join("service/config.json");
    let mut config: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    config["tick"]["every_s"] = serde_json::json!(2);
    config["health"]["every_s"] = serde_json::json!(1);
    fs::write(path, config.to_string()).unwrap();
    fs::write(f.0.join("comments.json"), "[]").unwrap();
    place_script(
        &f.0.join("gh"),
        r#"#!/usr/bin/python3
import json,pathlib,sys
r=pathlib.Path(__file__).parent;a=sys.argv[1:];cs=json.loads((r/'comments.json').read_text())
with (r/'gh-calls').open('a') as f:f.write(json.dumps(a)+'\n')
if a[:2]==['repo','view']:print(json.dumps({'defaultBranchRef':{'name':'main'},'nameWithOwner':'synthetic-owner/synthetic-repo','url':'https://github.invalid/synthetic-owner/synthetic-repo'}))
elif a[:2]==['issue','list']:print('[]')
elif a[0]=='api' and '/comments?' in a[1]:print(json.dumps(cs))
elif a[:3]==['issue','comment','901']:
    cs.append({'id':7001,'body':a[4],'created':2000,'updated':2000});(r/'comments.json').write_text(json.dumps(cs));print('https://github.invalid/synthetic-owner/synthetic-repo/issues/901#issuecomment-7001')
elif a==['issue','view','901','--json','comments']:
    print(json.dumps({'comments':[{'id':'syn-7001','author':None,'authorAssociation':'OWNER','body':c['body'],'createdAt':'2023-11-14T22:13:20Z','includesCreatedEdit':False,'isMinimized':False,'minimizedReason':None,'reactionGroups':[],'url':'https://github.invalid/synthetic-owner/synthetic-repo/issues/901#issuecomment-7001','viewerDidAuthor':True} for c in cs]}))
else:sys.exit(2)
"#,
    );
    let (child_stderr, child_stderr_sink) = CapturedStderr::new();
    let mut process = Process(
        std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "runtime::service_process", "--nocapture"])
            .env("OPENWIZ_T5_PROCESS_ROOT", &f.0)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(child_stderr_sink)
            .spawn()
            .unwrap(),
        child_stderr,
    );
    let until = Instant::now() + RUN_BUDGET;
    let status = loop {
        assert!(
            process.0.try_wait().unwrap().is_none(),
            "fixture service exited before health publication"
        );
        if let Ok(v) = openwiz_service::runtime::status(&f.0)
            && v["incidents"]
                .as_array()
                .is_some_and(|rows| rows.iter().any(|i| i["tries"]["first"]["comment"] == 7001))
            && v["tick"]["last_ended"]["how"] == "failed"
        {
            break v;
        }
        assert!(
            Instant::now() < until,
            "health job was not registered or did not complete its record"
        );
        std::thread::park_timeout(Duration::from_millis(5));
    };
    assert_eq!(
        status["incidents"][0]["tries"]["first"]["outcome"]["state"],
        "done"
    );
    assert!(f.0.join("other-job").exists());
    let rows: serde_json::Value =
        serde_json::from_slice(&fs::read(f.0.join("loops.json")).unwrap()).unwrap();
    assert_eq!(rows[0]["paused"], false);
    assert_eq!(rows[1]["paused"], true);
    assert_eq!(
        f.calls()
            .iter()
            .filter(|a| a[0] == "loop" && a[1] == "resume")
            .count(),
        1
    );
    drop(process);
}

#[test]
fn failed_replacement_does_not_report_the_stopped_server_as_running() {
    let mut server = super::server::server(Arc::new(|_| {}));
    let status = server.status_handle();
    let (control, requests) = channel();
    let mut jobs = Scheduler::default();
    assert!(status.running());
    let request = thread::spawn(move || control.restart_server(deadline()));
    assert!(
        !requests
            .recv_timeout(RUN_BUDGET)
            .unwrap()
            .apply(&mut jobs, &mut server, || Err(
                "synthetic bind failure".into()
            ))
    );
    assert!(request.join().unwrap().is_err());
    assert!(
        !status.running(),
        "a confirmed stopped listener must never keep its old running status"
    );
    server.join();
}
