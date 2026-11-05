//! One service process: embedded HTTP, private status IPC and registered jobs.
use crate::{
    document::{self, Document},
    paths,
    scheduler::Scheduler,
    state::{self, State},
};
use openwiz_server::{SendHost, WebRoot};
use serde_json::Value;
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::unix::{
        fs::{OpenOptionsExt, PermissionsExt},
        net::{UnixListener, UnixStream},
    },
    path::Path,
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const NOT_ANSWERING: &str = "service is not answering";
const IPC_TIMEOUT: Duration = Duration::from_secs(2);
pub fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|d| u64::try_from(d.as_millis()).ok())
        .unwrap_or(0)
}
struct Owner(File);
impl Drop for Owner {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

/// Blocks until a runtime error; its caller exits so the user unit restarts it.
pub fn run(root: &Path, web_path: &Path, build: &str, scheduler: Scheduler) -> Result<(), String> {
    run_with_binder(root, web_path, build, scheduler, openwiz_server::bind)
}

/// Inject socket creation without replacing the service's HTTP configuration,
/// startup guards, recovery, or scheduler. The binder transfers its listener.
pub fn run_with_binder(
    root: &Path,
    web_path: &Path,
    build: &str,
    scheduler: Scheduler,
    bind: impl FnOnce(u16) -> std::io::Result<std::net::TcpListener>,
) -> Result<(), String> {
    run_with_server(root, web_path, build, scheduler, |root, port, host, web| {
        let listener =
            bind(port).map_err(|_| "cannot bind the configured loopback port".to_owned())?;
        crate::web_api::start(root, listener, host, web)
    })
}

/// Explicit Rust source injection for recording fixtures; no environment or
/// CLI option can select these sources in the production service.
pub fn run_with_health_sources(
    root: &Path,
    web_path: &Path,
    build: &str,
    scheduler: Scheduler,
    bind: impl FnOnce(u16) -> std::io::Result<std::net::TcpListener>,
    sources: crate::health::Sources,
) -> Result<(), String> {
    run_composed(
        root,
        web_path,
        build,
        scheduler,
        |root, port, host, web| {
            let listener =
                bind(port).map_err(|_| "cannot bind the configured loopback port".to_owned())?;
            crate::web_api::start(root, listener, host, web)
        },
        Some(sources),
    )
}

fn run_with_server(
    root: &Path,
    web_path: &Path,
    build: &str,
    scheduler: Scheduler,
    start_server: impl FnOnce(
        &Path,
        u16,
        Option<SendHost>,
        WebRoot,
    ) -> Result<openwiz_server::Server, String>,
) -> Result<(), String> {
    run_composed(root, web_path, build, scheduler, start_server, None)
}

fn run_composed(
    root: &Path,
    web_path: &Path,
    build: &str,
    mut scheduler: Scheduler,
    start_server: impl FnOnce(
        &Path,
        u16,
        Option<SendHost>,
        WebRoot,
    ) -> Result<openwiz_server::Server, String>,
    sources: Option<crate::health::Sources>,
) -> Result<(), String> {
    if build.len() != 40
        || !build
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("build identity is unavailable; rebuild from Git or supply OPENWIZ_SERVICE_BUILD at build time".to_owned());
    }
    paths::inspect(root)?;
    paths::inspect_runtime(root)?;
    let text = fs::read_to_string(root.join("service/config.json"))
        .map_err(|_| "service/config.json: cannot read config".to_owned())?;
    let config = document::read(Document::Config, &text)
        .map_err(|why| format!("service/config.json: {why}"))?;
    let host = config["server"]["allowed_host"]
        .as_str()
        .map(SendHost::new)
        .transpose()
        .map_err(|why| format!("service/config.json: server.allowed_host: {why}"))?;
    let port = u16::try_from(config["server"]["port"].as_u64().unwrap())
        .map_err(|_| "service/config.json: invalid server.port".to_owned())?;
    let web = WebRoot::open(web_path)
        .map_err(|_| "the running build needs its web/ static export".to_owned())?;
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(root.join("service/run.lock"))
        .map_err(|_| "service/run.lock: cannot open private lock".to_owned())?;
    lock.try_lock()
        .map_err(|_| "service is already running".to_owned())?;
    let _owner = Owner(lock);
    paths::inspect(root)?;
    paths::inspect_runtime(root)?;
    let since = now();
    let mut state = State::load(root, since)?;
    let mut startup = crate::update::recover(root, &config, build, &mut state)?;
    state::status(&startup.preview(&state), build, since, port, None, since)?;
    let mut server = start_server(root, port, host.clone(), web.clone())?;
    // An injected binder can allocate its port atomically. Status and candidate
    // health confirmation must use the address the server actually owns.
    let port = server.local_addr().port();
    let server_since = Arc::new(Mutex::new((now(), server.status_handle())));
    let socket = root.join("service/status.sock");
    match fs::remove_file(&socket) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => {
            return Err(
                "service/status.sock: cannot remove the previous owner's socket".to_owned(),
            );
        }
    }
    let listener = UnixListener::bind(&socket)
        .map_err(|_| "service/status.sock: cannot bind private status socket".to_owned())?;
    fs::set_permissions(&socket, fs::Permissions::from_mode(0o600))
        .map_err(|_| "service/status.sock: cannot set private permissions".to_owned())?;
    let state = Arc::new(Mutex::new(state));
    let restart = Arc::new(std::sync::atomic::AtomicBool::new(false));
    crate::tick::register(root, &config, Arc::clone(&state), &mut scheduler)?;
    crate::events::intake::register(root, &config, &mut scheduler)?;
    // Refused loop authority/capacity never prevents independent service jobs.
    if crate::loops::production::register(root, &config, &mut scheduler).is_err() {
        eprintln!("openwiz-service: loop registration refused; inspect private configuration");
    }
    crate::update::register(
        root,
        &config,
        build,
        Arc::clone(&state),
        &mut scheduler,
        Arc::clone(&restart),
    )?;
    let (health_control, health_requests) =
        crate::health::runtime::channel_with_monitor(scheduler.tick_monitor());
    let sources = sources.unwrap_or_else(|| crate::health::Sources::production(root, &config));
    Arc::new(crate::health::Health::new(
        root,
        config.clone(),
        Arc::clone(&state),
        sources.room,
        sources.github,
        health_control,
    )?)
    .register(&mut scheduler, port, now)?;
    // #2034: the configured notification pass joins this scheduler. It reads
    // this service's own decisions route and saved health state. Delivery comes
    // from T4's one installed factory (#2035), or a fixture's recording one
    // (#2039); a refusal keeps other jobs.
    let (delivery, binding) = crate::delivery();
    match crate::notification_job(
        root,
        &config,
        Arc::clone(&state),
        crate::notifications::sources::loopback_decisions(port),
        crate::notifications::sources::installed_comments(&root.join("service/config.json")),
        delivery,
        binding,
        Arc::new(openwiz_server::SystemClock),
    ) {
        Ok(Some((every, job))) => scheduler
            .register(crate::NOTIFICATION_JOB, every, job)
            .map_err(str::to_owned)?,
        Ok(None) => {}
        Err(_) => eprintln!("openwiz-service: notification job refused; delivery stays off"),
    }
    let ipc_server_since = Arc::clone(&server_since);
    let build = build.to_owned();
    let ipc_state = Arc::clone(&state);
    let ipc_root = root.to_owned();
    // No client can observe the prior build's attempt under the new identity.
    // Hold publication until every startup component has been created.
    let mut publication = state.lock().map_err(|_| "service state unavailable")?;
    // A slow local reader can delay status only, never the job scheduler.
    let ipc = thread::Builder::new()
        .name("openwiz-service status".to_owned())
        .spawn(move || -> Result<(), String> {
            serve_status(listener.incoming(), &ipc_root, || {
                state::status(
                    ipc_state
                        .lock()
                        .map_err(|_| "service state is unavailable".to_owned())?
                        .snapshot(),
                    &build,
                    since,
                    port,
                    {
                        let status = ipc_server_since
                            .lock()
                            .map_err(|_| "server status is unavailable".to_owned())?;
                        status.1.running().then_some(status.0)
                    },
                    now(),
                )
            })
        })
        .map_err(|_| "cannot start the status listener".to_owned())?;
    startup.confirm(&mut publication, port)?;
    drop(publication);
    eprintln!("openwiz-service: running (loopback only)");
    let clock = Instant::now();
    loop {
        if restart.load(std::sync::atomic::Ordering::SeqCst) {
            return Err("checked update queued; handing over through the service unit".to_owned());
        }
        while let Ok(request) = health_requests.try_recv() {
            if request.apply(&mut scheduler, &mut server, || {
                let listener = openwiz_server::bind(port)
                    .map_err(|_| "cannot rebind the configured loopback port".to_owned())?;
                crate::web_api::start(root, listener, host.clone(), web.clone())
            }) {
                *server_since
                    .lock()
                    .map_err(|_| "server status is unavailable")? = (now(), server.status_handle());
            }
        }
        if server.unexpectedly_stopped() {
            return Err("embedded HTTP server stopped".to_owned());
        }
        if ipc.is_finished() {
            return Err("status listener stopped".to_owned());
        }
        scheduler
            .poll(clock.elapsed().as_secs())
            .map_err(|why| format!("the registered-job scheduler failed: {why}"))?;
        thread::park_timeout(Duration::from_millis(50));
    }
}

// Keep each local status request on the same IPC path as the running service.
fn serve_status(
    clients: impl IntoIterator<Item = std::io::Result<UnixStream>>,
    root: &Path,
    mut report: impl FnMut() -> Result<Value, String>,
) -> Result<(), String> {
    for client in clients {
        let mut client = client.map_err(|_| "status listener failed".to_owned())?;
        if client.set_write_timeout(Some(IPC_TIMEOUT)).is_err() {
            continue;
        }
        let value = match report() {
            Ok(value) => value,
            Err(why) => {
                eprintln!("openwiz-service: status report unavailable: {why}");
                continue;
            }
        };
        let Ok(value) = crate::update::record_status(root, value) else {
            eprintln!("openwiz-service: pending record status could not be read");
            continue;
        };
        let _ = client.write_all(value.to_string().as_bytes());
    }
    Err("status listener ended".to_owned())
}

/// Only reads the running process. A saved state file is never a live status.
pub fn status(root: &Path) -> Result<Value, String> {
    // Local inspectors return fixed path labels and rules, never file content.
    paths::inspect(root)?;
    paths::inspect_runtime(root)?;
    let query = || -> Result<Value, String> {
        let mut stream = UnixStream::connect(root.join("service/status.sock"))
            .map_err(|_| NOT_ANSWERING.to_owned())?;
        stream
            .set_read_timeout(Some(IPC_TIMEOUT))
            .map_err(|_| NOT_ANSWERING.to_owned())?;
        let mut text = String::new();
        stream
            .read_to_string(&mut text)
            .map_err(|_| NOT_ANSWERING.to_owned())?;
        document::read(Document::Status, &text)
    };
    query().map_err(|_| NOT_ANSWERING.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use openwiz_server::{Config, Limits, SystemClock};
    use std::{
        fs::DirBuilder,
        net::{TcpListener, TcpStream},
        os::unix::fs::DirBuilderExt,
        path::PathBuf,
        sync::{
            atomic::{AtomicU64, Ordering},
            mpsc,
        },
    };

    struct Fixture(PathBuf);
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    #[test]
    fn embedded_accept_thread_stopping_returns_a_runtime_error() {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let f = Fixture(std::env::temp_dir().join(format!(
            "ow-779-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        )));
        for path in [&f.0, &f.0.join("service"), &f.0.join("web")] {
            DirBuilder::new().mode(0o700).create(path).unwrap();
        }
        fs::write(f.0.join("web/index.html"), "synthetic page").unwrap();
        // Reserve the configured port until the injected constructor takes it.
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let addr = listener.local_addr().unwrap();
        let config = serde_json::json!({
            "schema": "openwiz.service-config.v1",
            "repository": {"owner": "synthetic-owner", "name": "synthetic-repo"},
            "project": "prj_syn_0001", "orchestrator_thread": "thr_syn_0001",
            "service_issue": 901, "github_app": {"app_id": 1001, "installation_id": 2002},
            "tick": {"every_s": 300}, "health": {"every_s": 60},
            "server": {"port": addr.port(), "allowed_host": null, "probe_timeout_s": 10}
        });
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(f.0.join("service/config.json"))
            .unwrap();
        file.write_all(config.to_string().as_bytes()).unwrap();
        drop(file);
        let (stopped_tx, stopped_rx) = mpsc::sync_channel(1);
        let (result_tx, result_rx) = mpsc::sync_channel(1);
        let root = f.0.clone();
        let runtime = thread::spawn(move || {
            let result = run_with_server(
                &root,
                &root.join("web"),
                &"a".repeat(40),
                Scheduler::default(),
                move |_, port, _, _| {
                    assert_eq!(port, addr.port());
                    // Zero slots force the accept thread itself to log a 503.
                    // A panic here ends the real accept thread, not a worker.
                    openwiz_server::start(
                        listener,
                        Config {
                            limits: Limits {
                                max_connections: 0,
                                ..Limits::default()
                            },
                            ..Config::default()
                        },
                        Arc::new(openwiz_adapter_cloudroom::source::CloudRoomSource::from_path()),
                        Arc::new(SystemClock),
                        Arc::new(move |_| {
                            stopped_tx.send(()).unwrap();
                            panic!("synthetic accept-thread stop");
                        }),
                    )
                    .map_err(|_| "synthetic server start failed".to_owned())
                },
            );
            result_tx.send(result).unwrap();
        });
        let _connection = TcpStream::connect(addr).unwrap();
        stopped_rx
            .recv_timeout(Duration::from_secs(5))
            .expect("accept thread never reached its stop");
        assert_eq!(
            result_rx
                .recv_timeout(Duration::from_secs(5))
                .expect("runtime stayed alive after HTTP accept thread stopped"),
            Err("embedded HTTP server stopped".to_owned()),
        );
        runtime.join().unwrap();
    }

    #[test]
    fn backward_clock_report_drops_only_its_client() {
        let state: Value = serde_json::from_str(include_str!("empty-state.json")).unwrap();
        let build = "0123456789abcdef0123456789abcdef01234567";
        let make_report = |at| state::status(&state, build, 1000, 7370, Some(1001), at);
        assert_eq!(
            make_report(999).unwrap_err(),
            "service document violates S6: a time after the report"
        );
        let mut clients = Vec::new();
        let mut peers = Vec::new();
        for _ in 0..3 {
            let (client, peer) = UnixStream::pair().unwrap();
            peer.set_read_timeout(Some(IPC_TIMEOUT)).unwrap();
            clients.push(Ok(client));
            peers.push(peer);
        }
        let mut times = [1001, 999, 1002].into_iter();
        // No pending journal exists here; no file is created by status reads.
        let root = std::env::temp_dir().join(format!("ow-778-{}", std::process::id()));
        assert!(!root.exists());
        assert_eq!(
            serve_status(clients, &root, || make_report(times.next().unwrap())),
            Err("status listener ended".to_owned())
        );
        assert_eq!(times.next(), None, "every request must be handled");
        for (peer, at) in peers.iter_mut().zip([Some(1001), None, Some(1002)]) {
            let mut text = String::new();
            peer.read_to_string(&mut text).unwrap();
            if let Some(at) = at {
                assert_eq!(
                    serde_json::from_str::<Value>(&text).unwrap(),
                    make_report(at).unwrap()
                );
            } else {
                assert!(text.is_empty(), "an invalid report must never be published");
            }
        }
        assert!(!root.exists(), "status reads must not write files");
    }
}
