//! The existing fleet tick as one scheduled job, with the service's App login.
use crate::{scheduler::Scheduler, state::State};
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_adapter_github::{process::Executor, tick::TickReads};
use openwiz_cli::fleet::tick::{self as fleet_tick, Args, Context};
use serde_json::{Value, json};
use std::{
    num::NonZeroU64,
    path::Path,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};

pub const JOB: &str = "fleet-tick";

pub struct Sources {
    pub github: Executor,
    pub room: CloudRoomSource,
}

pub fn register(
    root: &Path,
    config: &Value,
    state: Arc<Mutex<State>>,
    scheduler: &mut Scheduler,
) -> Result<(), String> {
    let app_root = root.to_owned();
    let app_config = config.to_string();
    // Open lazily: a missing App key is a failed scheduled run, never a
    // personal-account fallback or a reason to stop serving local status.
    // Cache only a successful construction so a later schedule can try again.
    let client = Mutex::new(None::<crate::app::Client>);
    let github = Executor::supplied(Arc::new(move |call, deadline| {
        let unavailable = || openwiz_core::source::SourceError::Unavailable {
            detail: "tick App request failed (details withheld)".to_owned(),
        };
        let app = {
            let mut client = client.lock().map_err(|_| unavailable())?;
            if client.is_none() {
                *client = Some(
                    crate::app::Client::from_config(&app_root, &app_config)
                        .map_err(|_| unavailable())?,
                );
            }
            client.as_ref().unwrap().clone()
        };
        app.execute(call, deadline).map_err(|_| unavailable())
    }));
    register_with_sources(
        root,
        config,
        state,
        scheduler,
        Sources {
            github,
            room: CloudRoomSource::from_path(),
        },
        crate::runtime::now,
    )
}

/// Production and recording fixtures share this configured composition. Only
/// the command sources and clock differ; cadence, context and state are the same.
pub fn register_with_sources(
    root: &Path,
    config: &Value,
    state: Arc<Mutex<State>>,
    scheduler: &mut Scheduler,
    sources: Sources,
    now: impl Fn() -> u64 + Send + Sync + 'static,
) -> Result<(), String> {
    let every = config["tick"]["every_s"]
        .as_u64()
        .and_then(NonZeroU64::new)
        .ok_or("tick schedule is invalid")?;
    let root = root.to_owned();
    let orchestrator = config["orchestrator_thread"].as_str().map(str::to_owned);
    let gh = TickReads::with_executor(sources.github);
    let project = config["project"]
        .as_str()
        .ok_or("tick project is invalid")?
        .to_owned();
    let authority = Arc::clone(&state);
    register_with_control(scheduler, every, state, now, move |stop| {
        let authority = Arc::clone(&authority);
        let control = fleet_tick::Control::new(&project, stop)
            .map_err(str::to_owned)?
            .with_fleet_authority(move |spec| {
                authority.lock().is_ok_and(|state| {
                    state
                        .snapshot()
                        .get("retired_loops")
                        .and_then(Value::as_array)
                        .is_none_or(|rows| {
                            rows.iter().all(|row| {
                                row["spec"].as_u64() != Some(spec.get())
                                    || row["phase"] != "pause_pending"
                            })
                        })
                })
            })
            // #2379: no trusted CP1 reader or Rust-to-Python bridge exists yet,
            // so every summary/close effect is refused with this fixed reason.
            .with_completion_verifier(|_| {
                Err("completion verification is unavailable; orchestrator judgment required: no trusted completion reader is installed")
            });
        fleet_tick::run_with_control(
            Args {
                due: false,
                dry_run: false,
                json: false,
            },
            Context {
                github: &gh,
                room: &sources.room,
                state: &root,
                orchestrator: orchestrator.as_deref(),
            },
            &mut std::io::stderr(),
            &control,
        )
        .map_err(str::to_owned)
    })
}

/// The scheduler and state seam used by fixture executors and controlled clocks.
/// The scheduler owns cadence and overlap; each invocation dispatches at most once.
pub fn register_with(
    scheduler: &mut Scheduler,
    every: NonZeroU64,
    state: Arc<Mutex<State>>,
    now: impl Fn() -> u64 + Send + Sync + 'static,
    execute: impl Fn() -> Result<(), String> + Send + Sync + 'static,
) -> Result<(), String> {
    register_with_control(scheduler, every, state, now, move |_| execute())
}

/// The stop flag belongs to the scheduler and is reset only after the old
/// handle has completed. An in-flight action keeps its durable outcome.
pub fn register_with_control(
    scheduler: &mut Scheduler,
    every: NonZeroU64,
    state: Arc<Mutex<State>>,
    now: impl Fn() -> u64 + Send + Sync + 'static,
    execute: impl Fn(Arc<AtomicBool>) -> Result<(), String> + Send + Sync + 'static,
) -> Result<(), String> {
    let stop = Arc::new(AtomicBool::new(false));
    let flag = Arc::clone(&stop);
    // If completion could not be persisted, retain it until the next schedule.
    // Repair that save before starting any new work; never replay the old run.
    let pending = Mutex::new(None::<Value>);
    let monitor = crate::scheduler::TickMonitor::default();
    let worker_monitor = monitor.clone();
    scheduler
        .register_tick(every, stop, monitor, move || {
            let result = (|| -> Result<(), String> {
                let mut pending = pending.lock().map_err(|_| "tick outcome unavailable")?;
                let started = now();
                {
                    let mut state = state.lock().map_err(|_| "tick state unavailable")?;
                    let mut value = state.snapshot().clone();
                    if let Some(ended) = pending.as_ref() {
                        value["tick"]["running"] = Value::Null;
                        value["tick"]["last_ended"] = ended.clone();
                        state.save(value.clone())?;
                        *pending = None;
                    }
                    if !value["tick"]["running"].is_null() {
                        return Err("previous tick outcome has not been saved".to_owned());
                    }
                    value["tick"]["running"] = json!({"started_at":started});
                    state.save(value)?;
                }
                let _run=worker_monitor.begin(started)?;
                let outcome = execute(Arc::clone(&flag));
                let ended = now().max(started);
                let mut state = state.lock().map_err(|_| "tick state unavailable")?;
                // Re-read under the lock: other jobs may have saved unrelated state.
                let mut value = state.snapshot().clone();
                value["tick"]["running"] = Value::Null;
                let ended = json!({
                    "started_at":started,"ended_at":ended,
                    "how":if flag.load(Ordering::SeqCst) { "stopped" } else if outcome.is_ok() { "finished" } else { "failed" }
                });
                value["tick"]["last_ended"] = ended.clone();
                *pending = Some(ended);
                state.save(value)?;
                *pending = None;
                outcome
            })();
            if result.is_err() {
                eprintln!("openwiz-service: scheduled fleet tick failed (details withheld)");
            }
        })
        .map_err(str::to_owned)
}
