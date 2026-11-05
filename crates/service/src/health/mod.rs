//! Health execution: save each try before effects, outcomes before records.
//! TK1 takeover persists exact-loop retirement and service-tick ownership.
pub mod loops;
mod model;
mod observe;
mod records;
pub mod runtime;
mod takeover;
mod watchdog;

/// Trusted embedding supplies complete observations, including authoritative
/// failure-disable provenance when such a producer exists.
pub type WatchdogRead = dyn Fn(u64) -> loops::Evidence<Vec<loops::Observation>> + Send + Sync;
use crate::{
    document::{self, Document},
    state::State,
};
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_adapter_github::{process::Executor, tick::TickReads};
use openwiz_core::{
    health::{self, model::*},
    messaging::{
        OpId,
        send::{self, SendRequest, Status},
        sha256_hex,
    },
    model::{SessionId, Timestamp},
};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::Instant,
};
pub struct Sources {
    pub room: CloudRoomSource,
    pub github: Executor,
}
impl Sources {
    /// Lazy App execution, pinned to this config. A missing key never falls
    /// back to the user's personal gh login or prevents local status startup.
    pub fn production(root: &Path, config: &Value) -> Self {
        let root = root.to_owned();
        let config = config.to_string();
        let client = Mutex::new(None::<crate::app::Client>);
        let github = Executor::supplied(Arc::new(move |call, deadline| {
            let unavailable = || openwiz_core::source::SourceError::Unavailable {
                detail: "health App request failed (details withheld)".into(),
            };
            let app = {
                let mut slot = client.lock().map_err(|_| unavailable())?;
                if slot.is_none() {
                    *slot = Some(
                        crate::app::Client::from_config(&root, &config)
                            .map_err(|_| unavailable())?,
                    );
                }
                slot.as_ref().unwrap().clone()
            };
            app.execute(call, deadline).map_err(|_| unavailable())
        }));
        Self {
            room: CloudRoomSource::from_path(),
            github,
        }
    }
}
pub trait RuntimeFixes: Send + Sync {
    fn restart_tick(&self, deadline: Instant) -> Result<(), String>;
    fn restart_server(&self, deadline: Instant) -> Result<(), String>;
    fn current_tick(&self) -> Result<Option<crate::scheduler::TickRun>, String> {
        Ok(None)
    }
    fn restart_stalled_tick(
        &self,
        _expected: crate::scheduler::TickRun,
        _deadline: Instant,
    ) -> Result<(), String> {
        Err("generation-checked tick repair is unavailable".into())
    }
}
struct Pending {
    id: String,
    slot: &'static str,
    outcome: Value,
}
pub struct Health {
    root: PathBuf,
    config: Value,
    state: Arc<Mutex<State>>,
    room: CloudRoomSource,
    github: Executor,
    runtime: Arc<dyn RuntimeFixes>,
    pending: Mutex<Option<Pending>>,
    watchdog: Arc<WatchdogRead>,
}
struct PassLock(std::fs::File);
impl Drop for PassLock {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}
impl Health {
    pub fn new(
        root: &Path,
        config: Value,
        state: Arc<Mutex<State>>,
        room: CloudRoomSource,
        github: Executor,
        runtime: Arc<dyn RuntimeFixes>,
    ) -> Result<Self, String> {
        document::read(Document::Config, &config.to_string())?;
        Ok(Self {
            root: root.to_owned(),
            config: config.clone(),
            state,
            room,
            github,
            runtime,
            pending: Mutex::new(None),
            watchdog: watchdog::installed(root, &config),
        })
    }
    /// Supply an authoritative observer for an embedded service. This grants
    /// no scheduler/write authority; absent provenance remains Unknown.
    pub fn with_watchdog_source(mut self, source: Arc<WatchdogRead>) -> Self {
        self.watchdog = source;
        self
    }
    pub fn observe(&self, port: u16) -> Result<Seen, String> {
        observe::read(self, port)
    }
    pub fn register(
        self: Arc<Self>,
        scheduler: &mut crate::scheduler::Scheduler,
        port: u16,
        now: impl Fn() -> u64 + Send + Sync + 'static,
    ) -> Result<(), String> {
        let every =
            std::num::NonZeroU64::new(self.config["health"]["every_s"].as_u64().unwrap()).unwrap();
        scheduler
            .register("health", every, move || {
                let result = self.observe(port).and_then(|seen| self.pass(&seen, now()));
                if result.is_err() {
                    eprintln!("openwiz-service: health pass incomplete (details withheld)");
                }
            })
            .map_err(str::to_owned)
    }
    fn snapshot(&self) -> Result<Value, String> {
        Ok(self
            .state
            .lock()
            .map_err(|_| "health state is unavailable")?
            .snapshot()
            .clone())
    }
    fn change(&self, change: impl FnOnce(&mut Value) -> Result<(), String>) -> Result<(), String> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "health state is unavailable")?;
        let mut value = state.snapshot().clone();
        change(&mut value)?;
        state.save(value)
    }
    fn repository(&self) -> Repository {
        Repository::parse(
            self.config["repository"]["owner"].as_str().unwrap(),
            self.config["repository"]["name"].as_str().unwrap(),
        )
        .unwrap()
    }
    fn patch(&self, id: &str, change: impl Fn(&mut Value)) -> Result<(), String> {
        self.change(|v| {
            let mut found = false;
            for field in ["incidents", "watchdog_deliveries"] {
                if let Some(rows) = v.get_mut(field).and_then(Value::as_array_mut) {
                    for incident in rows.iter_mut().filter(|i| i["id"] == id) {
                        change(incident);
                        found = true;
                    }
                }
            }
            if !found {
                return Err("health incident disappeared".into());
            }
            Ok(())
        })
    }
    fn save_outcome(&self, id: &str, slot: &str, outcome: &Value) -> Result<(), String> {
        self.change(|v| {
            let index = v["incidents"]
                .as_array()
                .unwrap()
                .iter()
                .position(|i| i["id"] == id)
                .ok_or("health incident disappeared")?;
            if outcome["owner"] == "service_tick" {
                let spec = v["incidents"][index]["spec"].clone();
                let thread = v["incidents"][index]["thread"].clone();
                let row = v["retired_loops"]
                    .as_array_mut()
                    .ok_or("takeover reservation missing")?
                    .iter_mut()
                    .find(|r| {
                        r["spec"] == spec
                            && r["thread"] == thread
                            && r["loop"] == outcome["retired_loop"]
                    })
                    .ok_or("takeover reservation disappeared")?;
                if row["phase"] != "paused" && row["phase"] != "active" {
                    return Err("takeover pause was not saved".into());
                }
                row["phase"] = json!("active");
            }
            v["incidents"][index]["tries"][slot]["outcome"] = outcome.clone();
            Ok(())
        })
    }
    fn recover(&self) -> Result<(), String> {
        let mut pending = self
            .pending
            .lock()
            .map_err(|_| "health outcome unavailable")?;
        if let Some(p) = pending.as_ref() {
            self.save_outcome(&p.id, p.slot, &p.outcome)?;
            *pending = None;
        }
        // A prior pass has returned and its lock is ours: no command is still
        // executing. Saved-but-unsettled tries count, and are never replayed.
        let snapshot = self.snapshot()?;
        if snapshot["incidents"].as_array().unwrap().iter().any(|i| {
            ["first", "second"]
                .iter()
                .any(|s| !i["tries"][s].is_null() && i["tries"][s]["outcome"].is_null())
        }) {
            self.change(|v| {
                for i in v["incidents"].as_array_mut().unwrap() {
                    if let Some(tries) = i.get_mut("tries") {
                        for s in ["first", "second"] {
                            if !tries[s].is_null() && tries[s]["outcome"].is_null() {
                                tries[s]["outcome"] = json!({"state":"interrupted"});
                            }
                        }
                    }
                }
                Ok(())
            })?;
        }
        Ok(())
    }
    pub fn pass(&self, seen: &Seen, now: u64) -> Result<(), String> {
        let _lock = PassLock(records::lock(&self.root)?);
        let deadline = Instant::now() + openwiz_core::limits::RUN_BUDGET;
        self.recover()?;
        let gh = TickReads::with_executor(self.github.clone());
        if !gh
            .repository(deadline)
            .map_err(|_| "health repository is unread")?
            .name
            .eq_ignore_ascii_case(&self.repository().to_string())
        {
            return Err("health repository does not match the service config".into());
        }
        let delivery_pending =
            self.flush_records(deadline)? | records::reconcile(&self.root, &self.github, deadline)?;
        let snapshot = self.snapshot()?;
        let before = model::incidents(&snapshot)?;
        let mut retired = takeover::rows(&snapshot)
            .iter()
            .map(|r| Id::parse(r["loop"].as_str().unwrap()).unwrap())
            .collect::<Vec<_>>();
        let mut seen = seen.clone();
        let mut bindings = Vec::new();
        if let Listed::Read(threads) = &mut seen.fleet_threads {
            for row in threads {
                if !matches!(row.seen, ThreadSeen::Archived | ThreadSeen::NotFound) {
                    continue;
                }
                match takeover::binding(self, row.spec, &row.thread, deadline) {
                    Ok(binding) => {
                        retired.push(binding.loop_id.clone());
                        if takeover::active(&snapshot, &binding) {
                            row.seen = ThreadSeen::Present;
                        } else {
                            bindings.push(binding);
                        }
                    }
                    Err(_) => {
                        row.seen = ThreadSeen::Unknown(Unread {
                            gap: Gap::CommandFailed,
                            reason: NonEmpty::new("fleet takeover authority is unread or changed")
                                .unwrap(),
                        })
                    }
                }
            }
        }
        // Fleet reads and HTTP probing may outlive the initially observed run.
        // Refresh after those reads, immediately before planning/saving a try.
        let observed_run = self.runtime.current_tick()?;
        let current = self.snapshot()?;
        let observed_run = observed_run.filter(|run| {
            current["tick"]["running"]["started_at"].as_u64() == Some(run.started_at)
        });
        seen.tick_running_since = observed_run
            .map(|run| {
                i64::try_from(run.started_at)
                    .map(Timestamp)
                    .map_err(|_| "tick start is out of range")
            })
            .transpose()?;
        let time = Timestamp(i64::try_from(now).map_err(|_| "health clock is out of range")?);
        let rules = Rules {
            repository: self.repository(),
            tick_every_s: std::num::NonZeroU64::new(
                self.config["tick"]["every_s"].as_u64().unwrap(),
            )
            .unwrap(),
        };
        let mut counter = 0;
        let mut new_id = || {
            counter += 1;
            OpId::parse(&sha256_hex(
                format!(
                    "openwiz.health.needs-you.v1\n{}\n{}\n{}\n{now}\n{counter}",
                    rules.repository, self.config["service_issue"], before.next_incident
                )
                .as_bytes(),
            ))
            .unwrap()
        };
        let plan = health::plan_with_retired(&before, &seen, &rules, time, &mut new_id, &retired);
        let loop_observations = (self.watchdog)(now);
        self.change(|v| {
            v["next_incident"] = json!(plan.incidents.next_incident);
            v["incidents"] = serde_json::to_value(&plan.incidents.incidents)
                .map_err(|_| "health incidents could not be encoded")?;
            v["last_pass"] =
                serde_json::to_value(&plan.pass).map_err(|_| "health pass could not be encoded")?;
            watchdog::apply(v, &snapshot, loop_observations, now, &mut new_id)?;
            for binding in &bindings {
                if plan.pass.fixes.iter().any(|f|matches!(f,Fix::TakeOverFleetThread{spec,thread,..} if *spec==binding.spec && *thread==binding.thread)){
                    takeover::reserve(v,binding,now);
                }
            }
            Ok(())
        })?;
        // Confirm every due retirement before any shared tick replacement.
        // A concurrent stalled-tick fix reuses this one bounded replacement.
        let mut prepared = Vec::new();
        for binding in &bindings {
            if plan.pass.fixes.iter().any(|f|matches!(f,Fix::TakeOverFleetThread{spec,thread,..} if *spec==binding.spec && *thread==binding.thread)) {
                prepared.push(takeover::prepare(self,binding,deadline).is_ok());
            }
        }
        let unconfirmed = takeover::rows(&self.snapshot()?)
            .iter()
            .any(|r| r["phase"] == "pause_pending");
        let takeover_tick = if prepared.is_empty() {
            None
        } else {
            Some(if prepared.iter().all(|ready| *ready) && !unconfirmed {
                self.runtime.restart_tick(deadline).map_err(|_| ())
            } else {
                Err(())
            })
        };
        for fix in &plan.pass.fixes {
            let (id, attempt, result, reason) = match fix {
                Fix::ResumeLoop {
                    incident,
                    attempt,
                    subject,
                } => (
                    *incident,
                    *attempt,
                    self.room
                        .resume_loop(&subject.id, &rules.repository, deadline)
                        .map(|()| json!({"state":"done"}))
                        .map_err(|_| ()),
                    "OpenWiz could not confirm the loop resume",
                ),
                Fix::RestartTick { incident, attempt } => (
                    *incident,
                    *attempt,
                    takeover_tick.unwrap_or_else(|| {
                        if unconfirmed {Err(())} else {observed_run.ok_or(()).and_then(|run|self.runtime.restart_stalled_tick(run,deadline).map_err(|_|()))}
                    }).map(|()| json!({"state":"done"})),
                    "OpenWiz could not confirm the tick restart",
                ),
                Fix::RestartServer { incident, attempt } => (
                    *incident,
                    *attempt,
                    self.runtime
                        .restart_server(deadline)
                        .map(|()| json!({"state":"done"}))
                        .map_err(|_| ()),
                    "OpenWiz could not confirm the server restart",
                ),
                Fix::TakeOverFleetThread {
                    incident,
                    attempt,
                    spec,
                    thread,
                } => (
                    *incident,
                    *attempt,
                    bindings
                        .iter()
                        .find(|b| b.spec == *spec && b.thread == *thread)
                        .ok_or(())
                        .and_then(|b|takeover_tick.unwrap_or(Err(())).map(|()| json!({"state":"done","owner":"service_tick","retired_loop":b.loop_id}))),
                    "OpenWiz could not confirm the fleet takeover",
                ),
            };
            let outcome = result.unwrap_or_else(
                |()| json!({"state":"failed","gap":"command_failed","reason":reason}),
            );
            let slot = if attempt == Try::First {
                "first"
            } else {
                "second"
            };
            let mut pending = self
                .pending
                .lock()
                .map_err(|_| "health outcome unavailable")?;
            *pending = Some(Pending {
                id: id.to_string(),
                slot,
                outcome: outcome.clone(),
            });
            self.save_outcome(&id.to_string(), slot, &outcome)?;
            *pending = None;
        }
        if self.flush_records(deadline)? || delivery_pending {
            return Err("health record or notification delivery remains unconfirmed; saved identities are retained".into());
        }
        Ok(())
    }
    fn flush_records(&self, deadline: Instant) -> Result<bool, String> {
        let mut pending = false;
        let snapshot = self.snapshot()?;
        let mut deliveries = snapshot["incidents"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|i| i["check"] != "watchdog")
            .collect::<Vec<_>>();
        if let Some(rows) = snapshot
            .get("watchdog_deliveries")
            .and_then(Value::as_array)
        {
            deliveries.extend(rows);
        }
        for i in deliveries {
            let id = i["id"].as_str().unwrap();
            let issue = Number::new(if i["check"] == "fleet_thread" {
                i["spec"].as_u64().unwrap()
            } else {
                self.config["service_issue"].as_u64().unwrap()
            })
            .unwrap();
            for slot in ["first", "second"] {
                let saved = &i["tries"][slot];
                if saved.is_null() || !saved["comment"].is_null() {
                    continue;
                }
                let Some(body) = records::frozen(
                    &self.root,
                    &format!("{issue}/{id}/{}/{slot}/{}", i["opened_at"], saved["at"]),
                    &records::render(i, Some(slot))?,
                )?
                else {
                    pending = true;
                    continue;
                };
                match records::post(&self.root, &self.github, issue, &body, deadline) {
                    Ok(comment) => {
                        self.patch(id, |v| v["tries"][slot]["comment"] = json!(comment))?
                    }
                    Err(_) => pending = true,
                }
            }
            if i["needs_you"].is_null() {
                continue;
            }
            let Some(body) = records::frozen(
                &self.root,
                &format!("{issue}/{}", i["needs_you"]["op_id"]),
                &records::render(i, None)?,
            )?
            else {
                pending = true;
                continue;
            };
            if i["needs_you"]["comment"].is_null() {
                match records::post(&self.root, &self.github, issue, &body, deadline) {
                    Ok(comment) => {
                        self.patch(id, |v| v["needs_you"]["comment"] = json!(comment))?
                    }
                    Err(_) => {
                        pending = true;
                        continue;
                    }
                }
            }
            let first = body.lines().next().ok_or("missing health record line")?;
            let message = format!(
                "Needs you:{} Recorded on #{issue}.",
                first
                    .strip_prefix("**Needs you:**")
                    .ok_or("invalid notification record")?
            );
            let op = OpId::parse(i["needs_you"]["op_id"].as_str().unwrap())
                .map_err(|_| "invalid saved notification id")?;
            let store = openwiz_store::FileStore::open(&self.root)
                .map_err(|_| "health notification store unavailable")?;
            let mut request = SendRequest::new(
                SessionId(
                    self.config["orchestrator_thread"]
                        .as_str()
                        .unwrap()
                        .to_owned(),
                ),
                message,
                op,
            );
            request.budget = deadline.saturating_duration_since(Instant::now());
            let report = send::send(
                &self.room.project_messenger(
                    Id::parse(self.config["project"].as_str().unwrap()).unwrap(),
                ),
                &store,
                &openwiz_server::SystemClock,
                &request,
            );
            if !matches!(report,Ok(ref report) if matches!(report.status,Status::Queued|Status::Accepted))
            {
                pending = true;
            } else if i["check"] == "watchdog" {
                self.change(|v| {
                    v["watchdog_deliveries"]
                        .as_array_mut()
                        .unwrap()
                        .retain(|row| row["id"] != i["id"]);
                    Ok(())
                })?;
            }
        }
        Ok(pending)
    }
}
