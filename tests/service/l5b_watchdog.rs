//! LP4 production health boundary on synthetic sources and private state only.
#[path = "../support/dirs.rs"]
mod dirs;
#[path = "l5b_observation.rs"]
mod observation;
use openwiz_core::{health::model::*, messaging::OpId};
use openwiz_service::{
    health::{
        Health, RuntimeFixes,
        loops::{Checking, Evidence, Observation},
    },
    state::State,
};
use serde_json::{Value, json};
use std::{
    fs,
    num::NonZeroU64,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::Instant,
};
struct Runtime;
impl RuntimeFixes for Runtime {
    fn restart_tick(&self, _: Instant) -> Result<(), String> {
        panic!("watchdog cannot repair")
    }
    fn restart_server(&self, _: Instant) -> Result<(), String> {
        panic!("watchdog cannot repair")
    }
}
struct World {
    root: PathBuf,
    config: Value,
    state: Arc<Mutex<State>>,
    source: Arc<Mutex<Evidence<Vec<Observation>>>>,
    comments: Arc<Mutex<Vec<Value>>>,
    lose: Arc<AtomicBool>,
}
impl Drop for World {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn id(s: &str) -> OpId {
    OpId::parse(s).unwrap()
}
fn row() -> Observation {
    Observation {
        loop_id: id("loop-synthetic"),
        next_due_at_ms: Evidence::Known(Some(1000)),
        checking: Evidence::Known(vec![Checking {
            run_id: id("run-synthetic"),
            started_at_ms: 1000,
            timeout_ms: NonZeroU64::new(100).unwrap(),
        }]),
        disabled_by_failures: Evidence::Known(true),
    }
}
fn healthy() -> Observation {
    Observation {
        loop_id: id("loop-synthetic"),
        next_due_at_ms: Evidence::Known(None),
        checking: Evidence::Known(vec![]),
        disabled_by_failures: Evidence::Known(false),
    }
}
fn seen() -> Seen {
    Seen {
        cloudroom: CloudRoomSeen::Running,
        loops: Listed::Read(vec![]),
        tick_running_since: None,
        fleet_threads: Listed::Read(vec![]),
        server: Known::Healthy,
    }
}
impl World {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-l5b-health-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        dirs::private_dir(&root).unwrap();
        dirs::private_dir(root.join("service")).unwrap();
        let config = json!({"schema":"openwiz.service-config.v1","repository":{"owner":"synthetic-owner","name":"synthetic-repo"},"project":"prj_syn_0001","orchestrator_thread":"thr_syn_0001","service_issue":901,"github_app":{"app_id":1001,"installation_id":2002},"tick":{"every_s":2},"health":{"every_s":60},"server":{"port":7370,"allowed_host":null,"probe_timeout_s":1}});
        fs::write(root.join("service/config.json"), config.to_string()).unwrap();
        fs::set_permissions(
            root.join("service/config.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        // Recording fake only; production discovery is never used.
        place_script(
            &root.join("room"),
            r#"#!/usr/bin/python3
import json,pathlib,sys
r=pathlib.Path(__file__).parent;a=sys.argv[1:]
with (r/'room-calls').open('a') as f: f.write(json.dumps(a)+'\n')
if a==['--version']: print('v127')
elif a[:2]==['thread','show']: print((r/'thread.json').read_text())
elif a[:2]==['thread','list']: print(json.dumps([{'id':'thr_syn_0001','queuedWork':'none','hasPendingInteraction':False}]))
elif a[:2]==['thread','tell']:
    if (r/'fail-tell').exists(): sys.exit(2)
    print((r/'tell.json').read_text())
else: sys.exit(2)
"#,
        );
        let mut thread: Value = serde_json::from_str(include_str!(
            "../fixtures/room-cli-0.43.1/normal/thread-show-0001.json"
        ))
        .unwrap();
        thread["thread"]["projectId"] = json!("prj_syn_0001");
        fs::write(root.join("thread.json"), thread.to_string()).unwrap();
        fs::write(
            root.join("tell.json"),
            include_str!("../fixtures/room-cli-0.43.1/send/tell-cloud-queue-observed.json"),
        )
        .unwrap();
        Self {
            state: Arc::new(Mutex::new(State::load(&root, 1000).unwrap())),
            root,
            config,
            source: Arc::new(Mutex::new(Evidence::Known(vec![row()]))),
            comments: Arc::new(Mutex::new(vec![])),
            lose: Arc::new(AtomicBool::new(false)),
        }
    }
    fn engine(&self) -> Health {
        let comments = self.comments.clone();
        let lose = self.lose.clone();
        let github = openwiz_adapter_github::process::Executor::supplied(Arc::new(
            move |call, _| {
                let args = call.argv().iter().map(String::as_str).collect::<Vec<_>>();
                let mut cs = comments.lock().unwrap();
                let value = match args.as_slice() {
                    ["repo", "view", ..] => {
                        json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic-owner/synthetic-repo","url":"https://github.invalid/synthetic-owner/synthetic-repo"})
                    }
                    ["api", path, ..] if path.contains("/comments?") => json!(*cs),
                    ["issue", "list", ..] => json!([]),
                    ["issue", "comment", "901", "--body", body] => {
                        let n = 7000 + cs.len() as u64;
                        cs.push(json!({"id":n,"body":body,"created":2000,"updated":2000}));
                        if lose.swap(false, Ordering::SeqCst) {
                            return Err(openwiz_core::source::SourceError::Unavailable {
                                detail: "synthetic lost reply".into(),
                            });
                        }
                        return Ok(format!("https://github.invalid/synthetic-owner/synthetic-repo/issues/901#issuecomment-{n}\n").into_bytes());
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
                Ok(value.to_string().into_bytes())
            },
        ));
        let source = self.source.clone();
        Health::new(
            &self.root,
            self.config.clone(),
            self.state.clone(),
            openwiz_adapter_cloudroom::source::CloudRoomSource::new(self.root.join("room")),
            github,
            Arc::new(Runtime),
        )
        .unwrap()
        .with_watchdog_source(Arc::new(move |_| source.lock().unwrap().clone()))
    }
    fn snapshot(&self) -> Value {
        self.state.lock().unwrap().snapshot().clone()
    }
    fn reload(&mut self) {
        self.state = Arc::new(Mutex::new(State::load(&self.root, 2000).unwrap()));
    }
    fn tells(&self) -> usize {
        fs::read_to_string(self.root.join("room-calls"))
            .unwrap_or_default()
            .lines()
            .filter(|l| serde_json::from_str::<Value>(l).unwrap()[1] == "tell")
            .count()
    }
}
#[test]
fn each_problem_notifies_once_across_reload_and_recovers_immediately() {
    let mut w = World::new();
    w.engine().pass(&seen(), 1101).unwrap();
    assert_eq!(w.snapshot()["incidents"].as_array().unwrap().len(), 3);
    assert_eq!(w.comments.lock().unwrap().len(), 3);
    assert_eq!(w.tells(), 3);
    w.reload();
    w.engine().pass(&seen(), 1200).unwrap();
    assert_eq!(w.comments.lock().unwrap().len(), 3);
    assert_eq!(w.tells(), 3);
    let mut changed = row();
    changed.next_due_at_ms = Evidence::Known(Some(1050));
    *w.source.lock().unwrap() = Evidence::Known(vec![changed]);
    w.engine().pass(&seen(), 1250).unwrap();
    assert_eq!(w.comments.lock().unwrap().len(), 4);
    assert_eq!(w.tells(), 4);
    *w.source.lock().unwrap() = Evidence::Unknown;
    w.engine().pass(&seen(), 1300).unwrap();
    assert_eq!(w.snapshot()["incidents"].as_array().unwrap().len(), 3);
    *w.source.lock().unwrap() = Evidence::Known(vec![healthy()]);
    w.engine().pass(&seen(), 1400).unwrap();
    assert_eq!(w.snapshot()["incidents"], json!([]));
    *w.source.lock().unwrap() = Evidence::Known(vec![row()]);
    w.engine().pass(&seen(), 1500).unwrap();
    assert_eq!(w.comments.lock().unwrap().len(), 7);
    assert_eq!(w.tells(), 7);
}
#[test]
fn changed_problem_notifies_and_uncertain_delivery_survives_healing() {
    let mut w = World::new();
    w.lose.store(true, Ordering::SeqCst);
    let first = w.engine().pass(&seen(), 1101);
    assert!(first.is_err());
    assert_eq!(w.snapshot()["incidents"].as_array().unwrap().len(), 3);
    *w.source.lock().unwrap() = Evidence::Known(vec![healthy()]);
    w.reload();
    w.engine().pass(&seen(), 1200).unwrap();
    assert_eq!(w.snapshot()["incidents"], json!([]));
    assert_eq!(w.comments.lock().unwrap().len(), 3);
    assert_eq!(w.tells(), 3);
    let mut changed = row();
    changed.next_due_at_ms = Evidence::Known(Some(1050));
    changed.checking = Evidence::Known(vec![]);
    changed.disabled_by_failures = Evidence::Known(false);
    *w.source.lock().unwrap() = Evidence::Known(vec![changed]);
    w.engine().pass(&seen(), 1300).unwrap();
    assert_eq!(w.comments.lock().unwrap().len(), 4);
    assert_eq!(w.snapshot()["incidents"][0]["broken"]["due_at_ms"], 1050);
}
#[test]
fn service_reader_accepts_exact_watchdog_faults_without_repairs() {
    let w = World::new();
    let mut state = w.snapshot();
    state["next_incident"] = json!(2);
    state["incidents"] = json!([{"id":"i1","check":"watchdog","loop_id":"loop-synthetic","opened_at":1101,"broken":{"state":"broken","what":"missed","due_at_ms":1000},"healthy_since":null,"needs_you":{"at":1101,"op_id":"syn-notification","comment":null}}]);
    openwiz_service::document::read(
        openwiz_service::document::Document::State,
        &state.to_string(),
    )
    .unwrap();
    let mut bad = state.clone();
    bad["incidents"][0]["tries"] = json!({"first":null,"second":null});
    assert!(
        openwiz_service::document::read(
            openwiz_service::document::Document::State,
            &bad.to_string()
        )
        .is_err()
    );
}

#[test]
fn registered_health_job_runs_the_watchdog() {
    let w = World::new();
    let server = openwiz_server::start(
        std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap(),
        openwiz_server::Config::default(),
        Arc::new(openwiz_adapter_cloudroom::source::CloudRoomSource::new(
            "/bin/false",
        )),
        Arc::new(openwiz_server::SystemClock),
        Arc::new(|_| {}),
    )
    .unwrap();
    let mut scheduler = openwiz_service::scheduler::Scheduler::default();
    Arc::new(w.engine())
        .register(&mut scheduler, server.local_addr().port(), || 1101)
        .unwrap();
    assert_eq!(scheduler.poll(60).unwrap(), ["health"]);
    scheduler.wait("health").unwrap();
    server
        .shutdown(Instant::now() + std::time::Duration::from_secs(3))
        .unwrap();
    server.join();
    assert_eq!(w.snapshot()["incidents"].as_array().unwrap().len(), 3);
    assert_eq!(w.comments.lock().unwrap().len(), 3);
    assert_eq!(w.tells(), 3);
}

#[test]
fn durable_reader_refuses_reusing_one_notification_for_distinct_problems() {
    let w = World::new();
    let mut state = w.snapshot();
    state["next_incident"] = json!(3);
    let first = json!({"id":"i1","check":"watchdog","loop_id":"loop-synthetic","opened_at":1101,"broken":{"state":"broken","what":"missed","due_at_ms":1000},"healthy_since":null,"needs_you":{"at":1101,"op_id":"syn-one-notification","comment":null}});
    let mut second = first.clone();
    second["id"] = json!("i2");
    second["broken"] = json!({"state":"broken","what":"disabled_by_failures"});
    state["incidents"] = json!([first, second]);
    assert!(
        openwiz_service::document::read(
            openwiz_service::document::Document::State,
            &state.to_string()
        )
        .is_err(),
        "two problems cannot share a send identity"
    );
}

#[test]
fn failed_cloudroom_delivery_remains_pending_after_healing_and_restart() {
    let mut w = World::new();
    fs::write(w.root.join("fail-tell"), "synthetic failed delivery").unwrap();
    assert!(w.engine().pass(&seen(), 1101).is_err());
    assert_eq!(w.tells(), 3);
    let pending = w.snapshot()["watchdog_deliveries"].clone();
    assert_eq!(pending.as_array().unwrap().len(), 3);
    *w.source.lock().unwrap() = Evidence::Known(vec![healthy()]);
    w.reload();
    assert!(w.engine().pass(&seen(), 1200).is_err());
    assert_eq!(w.snapshot()["incidents"], json!([]));
    assert_eq!(w.snapshot()["watchdog_deliveries"], pending);
    w.reload();
    assert!(w.engine().pass(&seen(), 1300).is_err());
    assert_eq!(w.snapshot()["incidents"], json!([]));
    assert_eq!(w.snapshot()["watchdog_deliveries"], pending);
    assert_eq!(w.comments.lock().unwrap().len(), 3);
    assert_eq!(
        w.tells(),
        3,
        "an uncertain or failed attempted send must not be repeated blindly"
    );
}

/// Places the executable `src` at `dst`, owner-only. A separate `cp` process
/// writes it, so this process never holds a writable descriptor for it: a
/// child another test forks meanwhile would inherit one until its exec and
/// keep the file busy, so launching it would fail with ETXTBSY (#2583, as
/// #2559 and #1754).
fn place(src: &std::path::Path, dst: &std::path::Path) {
    placed(copier(src, dst), dst);
}
/// Starts `place`'s `cp`, with no input and its output captured.
fn copier(src: &std::path::Path, dst: &std::path::Path) -> std::process::Child {
    use std::process::Stdio;
    // `cp` would copy into a directory and succeed (#2721, #2731).
    assert!(!dst.is_dir(), "{} is a directory", dst.display());
    std::process::Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("cp runs")
}
/// Waits for `place`'s `cp` to succeed, then makes `dst` executable, owner-only.
fn placed(cp: std::process::Child, dst: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    let out = cp.wait_with_output().expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    std::fs::set_permissions(dst, std::fs::Permissions::from_mode(0o700)).unwrap();
}
/// Places a fixture script the same way, from a source file that never runs.
fn place_script(dst: &std::path::Path, text: &str) {
    let src = dst.with_extension("src");
    std::fs::write(&src, text).unwrap();
    place(&src, dst);
    std::fs::remove_file(&src).unwrap();
}
/// Descriptors of this process open for writing on `path`'s file.
#[cfg(target_os = "linux")]
fn writers(path: &std::path::Path) -> usize {
    use std::os::unix::fs::MetadataExt;
    let (fds, infos) = (
        std::path::Path::new("/proc/self/fd"),
        std::path::Path::new("/proc/self/fdinfo"),
    );
    let target = std::fs::metadata(path).unwrap();
    std::fs::read_dir(fds)
        .unwrap()
        .filter_map(|fd| {
            let fd = fd.ok()?.file_name();
            let file = std::fs::metadata(fds.join(&fd)).ok()?;
            let info = std::fs::read_to_string(infos.join(&fd)).ok()?;
            let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
            let access = u32::from_str_radix(flags.trim(), 8).unwrap() & 3;
            (file.dev() == target.dev() && file.ino() == target.ino() && access != 0).then_some(())
        })
        .count()
}
/// #2583 (as #2559): this binary's fakes are placed while other test threads
/// fork. The copy is held mid-way on a FIFO, where this process must hold no
/// writer for the placed file; then the placed program launches.
#[cfg(target_os = "linux")]
#[test]
fn placing_a_fake_executable_leaves_no_writer_a_concurrent_fork_could_inherit() {
    let dir = PlaceDir::new("ow-place-l5b");
    let program = dir.0.join("placed");
    let held = writers_mid_copy(&dir.0, &program);
    assert_eq!(
        held, 0,
        "mid-copy, this process held a writable descriptor for the placed \
         executable: a child forked then keeps it busy (ETXTBSY)"
    );
    let run = std::process::Command::new(&program).output().unwrap();
    assert!(run.status.success());
    assert_eq!(run.stdout, b"PLACED\n");
}
/// #2731 (as #2721): a directory at the exact destination is refused,
/// instead of `cp` placing the program inside that directory and reporting
/// success.
#[test]
fn placing_onto_a_directory_destination_is_refused() {
    use std::os::unix::fs::DirBuilderExt;
    let dir = std::env::temp_dir().join(format!("ow-place-dir-l5b-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let destination = dir.join("placed");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&destination)
        .unwrap();
    let placed = std::panic::catch_unwind(|| place_script(&destination, "#!/bin/sh\nexit 0\n"));
    assert!(
        placed.is_err(),
        "a directory destination was accepted; the program landed inside it"
    );
    assert_eq!(std::fs::read_dir(&destination).unwrap().count(), 0);
    std::fs::remove_dir_all(&dir).unwrap();
}
/// #2699 (as #2594): the proof above fails, never hangs, when its copier fails
/// before opening the FIFO. Here `cp` cannot stat a destination under a
/// regular file.
#[cfg(target_os = "linux")]
#[test]
#[should_panic(expected = "the copier ended before opening the FIFO")]
fn the_fifo_proof_fails_when_its_copier_fails_before_the_rendezvous() {
    let dir = PlaceDir::new("ow-place-l5b-early");
    let file = dir.0.join("file");
    std::fs::write(&file, "").unwrap();
    writers_mid_copy(&dir.0, &file.join("placed"));
}
/// #2707, #2734: a copier still waiting on the FIFO when a proof fails is
/// killed and reaped as its `Copy` unwinds, never left behind. With no writer
/// started, the copier stays blocked opening the FIFO past the deadline.
#[cfg(target_os = "linux")]
#[test]
fn the_fifo_proof_reaps_a_copier_that_misses_its_deadline() {
    let dir = PlaceDir::new("ow-place-l5b-late");
    let fifo = dir.0.join("late.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let program = dir.0.join("placed");
    let cp = copier(&fifo, &program);
    let pid = cp.id();
    let unwound = std::panic::catch_unwind(move || {
        let _copy = Copy {
            source: None,
            cp: Some(cp),
            program,
            until: std::time::Instant::now(),
        };
        panic!("the proof failed while its copier waited");
    });
    assert!(unwound.is_err());
    let left = std::fs::metadata(format!("/proc/{pid}")).map(|_| ());
    assert_eq!(
        left.map_err(|e| e.kind()),
        Err(std::io::ErrorKind::NotFound),
        "the copier was left running or unreaped after the proof unwound"
    );
}
/// An owner-only scratch directory for one FIFO proof, removed when dropped,
/// even by a failing proof.
#[cfg(target_os = "linux")]
struct PlaceDir(std::path::PathBuf);
#[cfg(target_os = "linux")]
impl PlaceDir {
    fn new(prefix: &str) -> Self {
        use std::os::unix::fs::DirBuilderExt;
        let dir = std::env::temp_dir().join(format!("{prefix}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        Self(dir)
    }
}
#[cfg(target_os = "linux")]
impl Drop for PlaceDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
/// Places a script at `program` as `place` does, from a FIFO in `dir` this
/// process writes, and returns how many writers this process held for
/// `program` while the copy was held mid-way.
#[cfg(target_os = "linux")]
fn writers_mid_copy(dir: &std::path::Path, program: &std::path::Path) -> usize {
    use std::time::{Duration, Instant};
    let fifo = dir.join("source.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let mut copy = Copy::start(&fifo, program, Instant::now() + Duration::from_secs(10));
    let head = b"#!/bin/sh\n";
    copy.write(head);
    // Once the first bytes have landed, the placed file's writer is open.
    while std::fs::metadata(program).map_or(true, |m| m.len() < head.len() as u64) {
        copy.check("the copy started");
    }
    let held = writers(program);
    copy.write(b"printf 'PLACED\\n'\n");
    copy.finish();
    held
}
/// `place`'s `cp` copying a FIFO to `program`, and this process's writer for
/// that FIFO. Dropped, even by a failing proof, it closes the writer, so the
/// copier reads its end, then kills a copier still running after a short
/// grace and reaps it (#2707).
#[cfg(target_os = "linux")]
struct Copy {
    source: Option<std::fs::File>,
    cp: Option<std::process::Child>,
    program: std::path::PathBuf,
    until: std::time::Instant,
}
#[cfg(target_os = "linux")]
impl Copy {
    /// Starts the copier and opens the FIFO's writer once the copier's reader
    /// has it open, failing if the copier ends first or `until` passes.
    fn start(fifo: &std::path::Path, program: &std::path::Path, until: std::time::Instant) -> Self {
        let mut copy = Self {
            source: None,
            cp: Some(copier(fifo, program)),
            program: program.to_owned(),
            until,
        };
        // Opening blocks until a reader has the FIFO open, so it runs on its
        // own thread while this one watches the copier and the deadline.
        let opening = {
            let fifo = fifo.to_owned();
            std::thread::spawn(move || std::fs::OpenOptions::new().write(true).open(fifo))
        };
        while !opening.is_finished() {
            if copy.ended() || std::time::Instant::now() >= until {
                // A reader of this process's own completes the open; dropped
                // with it, so the copier sees an empty source if it opens late.
                let reader = std::fs::File::open(fifo);
                drop(opening.join());
                drop(reader);
                assert!(!copy.ended(), "the copier ended before opening the FIFO");
                panic!("the copier never opened the FIFO");
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        copy.source = Some(opening.join().unwrap().unwrap());
        copy
    }
    fn ended(&mut self) -> bool {
        self.cp
            .as_mut()
            .is_none_or(|cp| cp.try_wait().unwrap().is_some())
    }
    /// Fails if the copier has ended or `until` has passed; else waits a moment.
    fn check(&mut self, waiting_for: &str) {
        assert!(!self.ended(), "the copier ended before {waiting_for}");
        assert!(
            std::time::Instant::now() < self.until,
            "the deadline passed before {waiting_for}"
        );
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    fn write(&mut self, bytes: &[u8]) {
        use std::io::Write;
        self.source.as_mut().unwrap().write_all(bytes).unwrap();
    }
    /// Closes the writer and waits, by `until`, for the copier to succeed.
    fn finish(mut self) {
        drop(self.source.take());
        while !self.ended() {
            assert!(
                std::time::Instant::now() < self.until,
                "the copier never finished"
            );
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        placed(self.cp.take().unwrap(), &self.program);
    }
}
#[cfg(target_os = "linux")]
impl Drop for Copy {
    fn drop(&mut self) {
        drop(self.source.take());
        // The copier ends soon after its end of file: a short grace past a
        // missed deadline, never an unbounded wait.
        let now = std::time::Instant::now();
        let until = self.until.max(now + std::time::Duration::from_secs(1));
        while !self.ended() && std::time::Instant::now() < until {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        if let Some(mut cp) = self.cp.take() {
            let _ = cp.kill();
            let _ = cp.wait();
        }
    }
}
