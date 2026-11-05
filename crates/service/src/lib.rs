//! OpenWiz's PC service: a registered-job scheduler and the embedded HTTP API.
//! #269's approved exception permits this crate alone to depend on
//! openwiz-server. All HTTP routes and guards remain the server's own.
pub mod app;
pub mod bootstrap;
pub mod document;
pub mod events;
pub mod health;
pub mod loops;
pub mod notifications;
pub mod paths;
pub mod runtime;
pub mod scheduler;
pub mod state;
pub mod tick;
pub mod update;
mod web_api;
pub use web_api::start_notification_api;

/// Injected event entry point. Production transport belongs to #805.
pub use events::route_next as route_event;

use std::{path::PathBuf, process::ExitCode};

/// The registered notification job's name in the existing scheduler (#2034).
pub const NOTIFICATION_JOB: &str = "notifications";

/// #2034: construct the one bounded notification pass from configuration.
/// Absent `notifications` returns None: no store, no job and zero effects. The
/// scheduler never overlaps a job's runs; each pass ends by its run budget.
/// Delivery and binding verification are T4's; production passes
/// `UnavailableDelivery` and a verifier that refuses every binding.
/// A store briefly busy with an owner's write keeps the job: each pass retries
/// its safe initialization and submits nothing until it succeeds. Unsafe or
/// unreadable storage still refuses construction.
#[allow(clippy::too_many_arguments)]
pub fn notification_job(
    root: &std::path::Path,
    config: &serde_json::Value,
    state: std::sync::Arc<std::sync::Mutex<state::State>>,
    decisions: notifications::sources::DecisionsRead,
    comments: notifications::sources::CommentsRead,
    delivery: Box<dyn openwiz_core::notifications::boundary::DeliveryBoundary + Send>,
    binding: notifications::engine::BindingVerifier,
    clock: std::sync::Arc<dyn openwiz_core::ops::Clock>,
) -> Result<Option<(std::num::NonZeroU64, impl Fn() + Send + Sync + use<>)>, String> {
    use openwiz_core::notifications::model::Record;
    use openwiz_server::notifications::{Api, Read};
    use serde_json::json;
    use std::sync::Arc;
    let Some(job) = config.get("notifications") else {
        return Ok(None);
    };
    let every = job["every_s"]
        .as_u64()
        .and_then(std::num::NonZeroU64::new)
        .ok_or("notifications.every_s is invalid")?;
    let store = openwiz_store::notifications::Store::new(root);
    match store.initialize() {
        Ok(()) | Err(openwiz_store::notifications::Error::Busy) => {}
        Err(_) => return Err("service/notifications: protected store is unavailable".into()),
    }
    let read_state = Arc::clone(&state);
    let health: notifications::sources::HealthRead = Arc::new(move || {
        read_state
            .lock()
            .map(|s| s.snapshot().clone())
            .map_err(|_| openwiz_store::notifications::Error::Unavailable)
    });
    let sources = Arc::new(
        notifications::sources::Installed::new(
            config,
            decisions,
            health,
            comments,
            Arc::clone(&clock),
        )?
        .durable(root),
    );
    let ready = std::sync::atomic::AtomicBool::new(false);
    let engine = notifications::Engine::new(
        store.clone(),
        sources.clone(),
        delivery,
        Arc::clone(&clock),
        binding,
    );
    Ok(Some((every, move || {
        let deadline = clock.monotonic() + openwiz_core::limits::RUN_BUDGET;
        let ran = (|| {
            // Initialize and remember persisted open groups once, before the
            // first pass; a busy or unreadable store makes this pass submit
            // nothing and the next one try again.
            if !ready.load(std::sync::atomic::Ordering::SeqCst) {
                store.initialize()?;
                let saved = store.read()?;
                sources.seed(
                    saved
                        .groups
                        .iter()
                        .filter(|g| !g.closed)
                        .map(|g| &g.observation),
                );
                ready.store(true, std::sync::atomic::Ordering::SeqCst);
            }
            engine.run(deadline)
        })();
        if ran.is_ok() {
            sources.settle();
        }
        let now = u64::try_from(clock.now().0).unwrap_or(0);
        let status = engine.read(Read::Status, now, deadline).ok();
        let Ok(mut saved) = state.lock() else {
            eprintln!("openwiz-service: notification state is unavailable");
            return;
        };
        let previous = saved.snapshot()["notifications"].clone();
        let (words, generation, reason) = match status.map(|d| d.record) {
            Some(Record::Status(s)) => (
                json!(s.state),
                json!(s.preferences.generation),
                json!(s.reason),
            ),
            _ => (
                json!("unavailable"),
                previous
                    .get("preference_generation")
                    .cloned()
                    .unwrap_or(json!(0)),
                json!("Notification status is unread"),
            ),
        };
        let summary = if ran.is_ok() {
            json!({"state":words,"preference_generation":generation,"last_pass_at":{"known":now},"reason":reason})
        } else {
            let last = match previous.get("last_pass_at") {
                Some(last) if last["known"].is_u64() => last.clone(),
                _ => json!({"unknown":"No completed notification source pass"}),
            };
            json!({"state":words,"preference_generation":generation,"last_pass_at":last,
                "reason":"Notification source pass did not complete; no new submission"})
        };
        if saved.publish_notifications(summary).is_err() || ran.is_err() {
            eprintln!("openwiz-service: notification pass incomplete; delivery stays unproven");
        }
    })))
}

/// The commit the service programs were built from, never a guessed identity.
pub const BUILD: &str = env!("OPENWIZ_SERVICE_BUILD");
/// RL4 (#1148): this program's compiled product identity, one record (prefix,
/// canonical JSON, LF) in its read-only data; the build script writes the JSON
/// (contracts/release-candidate.v1.md, "Minimum product identity").
pub static PRODUCT: [u8; IDENTITY.len() + 20] = product_record(IDENTITY);
const IDENTITY: &str = match option_env!("OPENWIZ_PRODUCT_IDENTITY") {
    Some(json) => json,
    None => "",
};

const fn product_record<const N: usize>(json: &str) -> [u8; N] {
    let (prefix, json) = (b"OPENWIZ_PRODUCT_V1:", json.as_bytes());
    let mut record = [b'\n'; N];
    let mut at = 0;
    while at < N - 1 {
        record[at] = if at < 19 { prefix[at] } else { json[at - 19] };
        at += 1;
    }
    record
}

/// `--build-identity`: print the compiled identity and nothing else. It reads
/// no state or account, calls no `room-cli` and binds nothing. An unknown
/// identity refuses.
fn build_identity() -> std::process::ExitCode {
    use std::io::Write;
    // Past the 19-byte prefix: naming the prefix again would add a second record.
    if !IDENTITY.is_empty() && std::io::stdout().write_all(&PRODUCT[19..]).is_ok() {
        return std::process::ExitCode::SUCCESS;
    }
    eprintln!("build identity is unavailable");
    std::process::ExitCode::FAILURE
}

const HELP: &str = "openwiz-service: OpenWiz's PC service\n\nUsage: openwiz-service\n       openwiz-service status [--json]\n       openwiz-service --help\n\nReads service/config.json under the OpenWiz state directory. Serves the running\nbuild's web/ on loopback only. No jobs register until their own tickets land.\nStatus queries the private local socket; an absent service exits 1 with no JSON.\n";

/// The real program and the test-only example share every dispatch path.
pub fn dispatch(discovery: openwiz_adapter_cloudroom::locate::Discovery) -> ExitCode {
    dispatch_with_jobs(discovery, scheduler::Scheduler::default())
}

/// A delivery adapter and its binding verifier, built once per engine.
pub type DeliveryFactory = std::sync::Arc<
    dyn Fn() -> (
            Box<dyn openwiz_core::notifications::boundary::DeliveryBoundary + Send>,
            notifications::engine::BindingVerifier,
        ) + Send
        + Sync,
>;
static DELIVERY: std::sync::OnceLock<DeliveryFactory> = std::sync::OnceLock::new();

/// #2039 (Q2-A): the job's and the web API's delivery. Only
/// `dispatch_with_delivery` sets another factory; production uses T4's
/// `delivery::installed`.
pub(crate) fn delivery() -> (
    Box<dyn openwiz_core::notifications::boundary::DeliveryBoundary + Send>,
    notifications::engine::BindingVerifier,
) {
    DELIVERY
        .get()
        .map_or_else(notifications::delivery::installed, |factory| factory())
}

/// Explicit Rust injection of a recording delivery for fixture programs, with
/// the real dispatch otherwise unchanged. No CLI or environment setting selects it.
pub fn dispatch_with_delivery(
    discovery: openwiz_adapter_cloudroom::locate::Discovery,
    jobs: scheduler::Scheduler,
    factory: DeliveryFactory,
) -> ExitCode {
    if DELIVERY.set(factory).is_err() {
        eprintln!("openwiz-service: delivery already configured");
        return ExitCode::FAILURE;
    }
    dispatch_with_jobs(discovery, jobs)
}

/// Registered jobs join the same process runtime. Production starts with none.
pub fn dispatch_with_jobs(
    discovery: openwiz_adapter_cloudroom::locate::Discovery,
    jobs: scheduler::Scheduler,
) -> ExitCode {
    dispatch_with_binder(discovery, jobs, openwiz_server::bind)
}

/// Explicit Rust injection for fixture programs; ordinary dispatch always uses
/// the configured loopback port. No CLI or environment setting selects a binder.
pub fn dispatch_with_binder(
    discovery: openwiz_adapter_cloudroom::locate::Discovery,
    jobs: scheduler::Scheduler,
    bind: impl FnOnce(u16) -> std::io::Result<std::net::TcpListener>,
) -> ExitCode {
    std::panic::set_hook(Box::new(|_| eprintln!("openwiz-service: internal error")));
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args == ["--build-identity"] {
        return build_identity();
    }
    if args == ["--update-build"] {
        println!("{BUILD}");
        return ExitCode::SUCCESS;
    }
    if args == ["--help"] || args == ["-h"] {
        print!("{HELP}");
        return ExitCode::SUCCESS;
    }
    let query = args == ["status"] || args == ["status", "--json"];
    if !args.is_empty() && !query {
        eprintln!("openwiz-service: usage: openwiz-service [status [--json] | --help]");
        return ExitCode::from(2);
    }
    let result = (|| -> Result<(), String> {
        let root =
            openwiz_store::default_state_dir(&|name| std::env::var_os(name)).map_err(|e| e.0)?;
        if query {
            let status = runtime::status(&root)?;
            if args.len() == 2 {
                println!("{status}");
            } else {
                println!(
                    "OpenWiz service: running\nBuild: {}\nSince: {}\nServer: 127.0.0.1:{}",
                    status["service"]["build"].as_str().unwrap(),
                    status["service"]["since"],
                    status["server"]["port"]
                );
            }
            return Ok(());
        }
        openwiz_adapter_cloudroom::locate::install(discovery)
            .map_err(|_| "discovery already configured".to_owned())?;
        let exe =
            std::env::current_exe().map_err(|_| "cannot locate the running build".to_owned())?;
        bootstrap::check(&exe)?;
        let web = exe
            .parent()
            .map(|p| p.join("web"))
            .unwrap_or_else(PathBuf::new);
        runtime::run_with_binder(&root, &web, BUILD, jobs, bind)
    })();
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(why) => {
            eprintln!("openwiz-service: {why}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod product_identity {
    #[test]
    fn the_compiled_record_is_this_programs_canonical_identity() {
        let json = std::str::from_utf8(&super::PRODUCT)
            .unwrap()
            .strip_prefix("OPENWIZ_PRODUCT_V1:")
            .and_then(|r| r.strip_suffix('\n'))
            .unwrap();
        let value: std::collections::BTreeMap<String, String> = serde_json::from_str(json).unwrap();
        assert_eq!(
            serde_json::to_string(&value).unwrap(),
            json,
            "canonical JSON"
        );
        let keys: Vec<_> = value.keys().map(String::as_str).collect();
        assert_eq!(keys, ["product", "schema", "source", "target", "version"]);
        assert_eq!(value["product"], "service");
        assert_eq!(value["schema"], "openwiz.product.v1");
        assert_eq!(value["version"], env!("CARGO_PKG_VERSION"));
    }
}
