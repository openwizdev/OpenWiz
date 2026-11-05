//! Run approved immutable default-branch definitions through the core planner.
//! Production must supply a trusted approval verifier and explicit capacities;
//! this module provides no default authority, limits, or live activation.
pub mod approval;
mod check;
pub mod limits;
pub mod production;
mod repository;
mod storage;
use openwiz_core::{
    loops::{self as model, Limits},
    messaging::{OpId, sha256_hex},
    new_thread::{
        Binding,
        operation::{NewThreadClient, PreviewVerdict, new_thread, preview_new_thread},
        outcome::Outcome,
        record::NewThreadStore,
    },
    ops::Clock,
    prompt::attachments_digest,
};
use repository::{Definition, Repository};
use serde_json::{Value, json};
use std::{num::NonZeroU64, path::PathBuf, sync::Arc};
use storage::Storage;

pub struct Config {
    /// Deployment maintains this checkout and its origin/HEAD default ref.
    pub checkout: PathBuf,
    /// Existing owner-only OpenWiz state, outside the repository.
    pub state: PathBuf,
    pub limits: Option<Limits>,
}

pub trait Approval: Send + Sync {
    /// Positive verification of the referenced approval for this exact blob.
    /// A schema pass, merged file or nonempty authority string is insufficient.
    fn verify(&self, definition: &Value, revision: &str) -> bool;
}

pub struct Services {
    pub clock: Arc<dyn Clock>,
    pub client: Arc<dyn NewThreadClient>,
    /// The existing new-thread store, rooted in Config.state.
    pub new_threads: Arc<dyn NewThreadStore>,
    pub approval: Option<Arc<dyn Approval>>,
}

pub struct Runner {
    config: Config,
    services: Services,
}
impl Runner {
    pub fn new(config: Config, services: Services) -> Self {
        Self { config, services }
    }
    /// Register with the existing always-on runtime. The caller supplies the
    /// polling period; the loops planner retains each original occurrence.
    pub fn register(
        self,
        scheduler: &mut crate::scheduler::Scheduler,
        every_s: NonZeroU64,
    ) -> Result<(), String> {
        self.valid_limits()?;
        scheduler.register("loops.v1",every_s,move||{
            if self.pass().is_err(){eprintln!("openwiz-service: loop pass refused; inspect private loop state and configuration");}
        }).map_err(str::to_owned)
    }
    fn valid_limits(&self) -> Result<Limits, String> {
        let limits = self
            .config
            .limits
            .ok_or("shared loop capacities were not supplied")?;
        if [limits.checks, limits.agents]
            .iter()
            .any(|c| c.urgent_reserve > c.max)
        {
            return Err("invalid shared loop capacities".to_owned());
        }
        Ok(limits)
    }
    fn approved(&self, d: &Definition) -> bool {
        self.services
            .approval
            .as_ref()
            .is_some_and(|approval| approval.verify(&d.value, &d.revision))
    }
    fn now(&self) -> Result<u64, String> {
        u64::try_from(self.services.clock.now().0)
            .map_err(|_| "loop clock precedes epoch".to_owned())
    }
    /// One serialized pass: re-read state under lock, reconcile without
    /// dispatch, plan checks, then independently plan dispatch admission.
    pub fn pass(&self) -> Result<Vec<Value>, String> {
        let state = Storage::open(&self.config.state)?;
        let limits = match self.valid_limits() {
            Ok(limits) => limits,
            Err(reason) => {
                state.save(
                    "admission.json",
                    &json!({"at_ms":self.now()?,"reason":reason}),
                )?;
                return Err(reason);
            }
        };
        let repository = Repository(self.config.checkout.clone());
        let definitions = repository.current()?;
        let refused:Vec<_>=definitions.iter().filter(|d|!self.approved(d)).map(|d|json!({
            "loop_id":d.value["id"],"definition_revision":d.revision,"reason":"Exact definition approval is not verified."
        })).collect();
        state.save(
            "admission.json",
            &json!({"at_ms":self.now()?,"refused":refused}),
        )?;
        let mut runs = state.runs()?;
        let mut switches = state.switches()?;
        for d in &definitions {
            switches
                .entry(d.value["id"].as_str().unwrap())
                .or_insert_with(|| d.value["enabled"].clone());
        }
        // Validate the complete history before updating even one record.
        let projected = self.snapshot(&repository, &definitions, &runs, &switches)?;
        model::plan(&projected, self.now()?, &limits)
            .map_err(|_| "invalid loop snapshot".to_owned())?;
        state.save_switches(&switches)?;
        for run in &mut runs {
            if run["result"]["kind"] == "checking" {
                self.update(&state,run,json!({"kind":"check_failed","reason":"Service stopped during the check; the occurrence is not retried."}))?;
            } else if matches!(
                run["result"]["kind"].as_str(),
                Some("dispatching" | "uncertain")
            ) {
                self.reconcile(&repository, &state, run)?;
            }
        }
        let snapshot = self.snapshot(&repository, &definitions, &runs, &switches)?;
        let plan = model::plan(&snapshot, self.now()?, &limits)
            .map_err(|_| "invalid loop snapshot".to_owned())?;
        for action in plan.due {
            if let model::Action::Check {
                loop_id,
                revision,
                occurrence: model::Occurrence::Scheduled { due_at_ms },
            } = action
            {
                let d = definitions
                    .iter()
                    .find(|d| d.value["id"] == loop_id.as_str() && d.revision == revision.as_str())
                    .ok_or("missing planned definition")?;
                if !self.approved(d) {
                    continue;
                }
                let wake = json!({"kind":d.value["wake"]["kind"],"due_at_ms":due_at_ms});
                let digest =
                    sha256_hex(format!("openwiz.loop.run.v1:{}:{}", loop_id, wake).as_bytes());
                let id = format!("lr{}", &digest[..62]);
                let now = self.now()?;
                let mut run = json!({"schema":"openwiz.loops.v1","kind":"run","id":id,"loop_id":loop_id.as_str(),"definition_revision":d.revision,"wake":wake,
                    "started_at_ms":now,"updated_at_ms":now,"cost":{"kind":"unknown","reason":"Not reported."},"result":{"kind":"checking"}});
                state.save_run(&run)?;
                let mut result = check::run(
                    &self.config.checkout,
                    &d.value["check"],
                    self.services.clock.as_ref(),
                );
                if result["kind"] == "deferred" && d.value["mode"] == "shadow" {
                    result = json!({"kind":"shadow","finding":result["finding"]});
                }
                self.update(&state, &mut run, result)?;
                runs.push(run);
            }
        }
        let mut snapshot = self.snapshot(&repository, &definitions, &runs, &switches)?;
        snapshot.active_agents = self.occupancy(&state, &runs)?;
        let plan = model::plan(&snapshot, self.now()?, &limits)
            .map_err(|_| "invalid loop dispatch snapshot".to_owned())?;
        for action in plan.due {
            if let model::Action::Dispatch { run_id } = action {
                let run = runs
                    .iter_mut()
                    .find(|r| r["id"] == run_id.as_str())
                    .ok_or("missing planned run")?;
                let definition = repository.blob(run["definition_revision"].as_str().unwrap())?;
                // Recheck authority at the last effect boundary too.
                if !self.approved(&definition) {
                    let finding = run["result"]["finding"].clone();
                    self.update(&state,run,json!({"kind":"refused","finding":finding,"reason":"Exact definition approval is not verified."}))?;
                    continue;
                }
                let finding = run["result"]["finding"].as_str().unwrap().to_owned();
                let request = definition.request(&finding, run_id.clone());
                if request.validate().is_err() {
                    self.update(&state,run,json!({"kind":"refused","finding":finding,"reason":"Complete brief and finding do not pass new-thread validation."}))?;
                    continue;
                }
                // Reuse the same public preview gates before reserving an
                // attempted start. A refusal here consumes no start budget.
                let ready = preview_new_thread(
                    self.services.client.as_ref(),
                    self.services.clock.as_ref(),
                    &request,
                )
                .is_ok_and(|preview| matches!(preview.verdict, PreviewVerdict::Ready { .. }));
                if !ready || !self.approved(&definition) {
                    self.update(&state,run,json!({"kind":"refused","finding":finding,"reason":"Existing new-thread gates or exact approval refused before dispatch."}))?;
                    continue;
                }
                // A failed durable save ends the pass before any create.
                self.update(&state,run,json!({"kind":"dispatching","finding":finding,"op_id":run_id.as_str(),"dispatch_at_ms":self.now()?}))?;
                // All existing project/catalogue/prompt/write gates remain.
                // Read the saved outcome, even when the call's report could
                // not be saved. An error or missing receipt stays uncertain.
                let _ = new_thread(
                    self.services.client.as_ref(),
                    self.services.new_threads.as_ref(),
                    self.services.clock.as_ref(),
                    &request,
                );
                self.reconcile(&repository, &state, run)?;
            }
        }
        state.runs()
    }
    fn update(&self, state: &Storage, run: &mut Value, result: Value) -> Result<(), String> {
        let now = self.now()?;
        if now < run["updated_at_ms"].as_u64().unwrap() {
            return Err("loop clock went backwards".to_owned());
        }
        let mut next = run.clone();
        next["updated_at_ms"] = json!(now);
        next["result"] = result;
        state.save_run(&next)?;
        *run = next;
        Ok(())
    }
    fn reconcile(&self, repo: &Repository, state: &Storage, run: &mut Value) -> Result<(), String> {
        let previous = &run["result"];
        let op_id = OpId::parse(previous["op_id"].as_str().unwrap()).unwrap();
        let d = repo.blob(run["definition_revision"].as_str().unwrap())?;
        let request = d.request(previous["finding"].as_str().unwrap(), op_id.clone());
        let record = self
            .services
            .new_threads
            .inspect(&op_id, self.services.clock.now())
            .map_err(|_| "cannot inspect saved new-thread outcome".to_owned())?;
        let mut result = json!({"kind":"uncertain","finding":previous["finding"],"op_id":op_id.as_str(),"dispatch_at_ms":previous["dispatch_at_ms"],"reason":"No confirmed saved new-thread receipt; never retried."});
        if let Some(record) = record {
            if record.op_id != op_id
                || !record
                    .binding
                    .differences(&Binding::new(&request, attachments_digest(&[])))
                    .is_empty()
            {
                return Err("new-thread receipt differs from the saved loop request".to_owned());
            }
            match record.outcome {
                Some(Outcome::Created { thread_id, .. }) => {
                    result["kind"] = json!("created");
                    result.as_object_mut().unwrap().remove("reason");
                    result["thread_id"] = json!(thread_id);
                }
                Some(Outcome::Refused { .. } | Outcome::Failed { .. }) => {
                    result["kind"] = json!("not_created");
                    result["reason"] = json!("Existing new-thread outcome confirms no creation.");
                }
                _ => {}
            }
        }
        if result != run["result"] {
            self.update(state, run, result)?;
        }
        Ok(())
    }
    fn snapshot(
        &self,
        repo: &Repository,
        definitions: &[Definition],
        runs: &[Value],
        switches: &serde_json::Map<String, Value>,
    ) -> Result<model::Snapshot, String> {
        let definitions = definitions
            .iter()
            .map(|d| {
                d.project(
                    switches[d.value["id"].as_str().unwrap()].as_bool().unwrap()
                        && self.approved(d),
                )
            })
            .collect();
        let projected = runs
            .iter()
            .map(|run| project_run(repo, run))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(model::Snapshot {
            definitions,
            runs: projected,
            // Validation and check admission need no live occupancy reads.
            active_agents: None,
        })
    }
    fn occupancy(
        &self,
        state: &Storage,
        runs: &[Value],
    ) -> Result<Option<Vec<model::ActiveAgent>>, String> {
        let created: std::collections::BTreeMap<_, _> = runs
            .iter()
            .filter(|r| r["result"]["kind"] == "created")
            .map(|r| (r["id"].as_str().unwrap(), &r["result"]["thread_id"]))
            .collect();
        let mut saved = state.settled_agents()?.unwrap_or(json!({}));
        let settled = saved.as_object_mut().ok_or("invalid settled loop agents")?;
        if settled.iter().any(|(id, thread)| {
            created
                .get(id.as_str())
                .is_none_or(|expected| *expected != thread)
        }) {
            return Err("settled agent differs from its created run".to_owned());
        }
        let mut changed = false;
        let mut active = Some(Vec::new());
        for (id, thread) in created {
            if settled.contains_key(id) {
                continue;
            }
            let read = self.services.client.show_thread(
                thread.as_str().unwrap(),
                self.services.clock.monotonic() + openwiz_core::limits::READ_TIMEOUT,
            );
            match read.ok().map(|s| s.status) {
                Some(openwiz_core::model::Fact::Known(status)) => match status.as_str() {
                    "pending" | "starting" | "active" => {
                        if let Some(active) = &mut active {
                            active.push(model::ActiveAgent {
                                run_id: OpId::parse(id).unwrap(),
                            });
                        }
                    }
                    "idle" | "error" => {
                        settled.insert(id.to_owned(), thread.clone());
                        changed = true;
                    }
                    _ => active = None,
                },
                _ => active = None,
            }
        }
        if changed {
            state.save("settled.json", &saved)?;
        }
        Ok(active)
    }
}
fn project_run(repo: &Repository, run: &Value) -> Result<model::Run, String> {
    let d = repo.blob(run["definition_revision"].as_str().unwrap())?;
    if d.value["id"] != run["loop_id"] || d.value["wake"]["kind"] != run["wake"]["kind"] {
        return Err("run differs from its immutable definition".to_owned());
    }
    let wake = &run["wake"];
    let original = &d.value["wake"];
    let due = wake["due_at_ms"].as_u64().unwrap_or(0);
    let matches = match original["kind"].as_str().unwrap() {
        "once" => original["at_ms"].as_u64() == Some(due),
        "interval" => due
            .checked_sub(original["anchor_ms"].as_u64().unwrap())
            .is_some_and(|offset| offset % original["every_ms"].as_u64().unwrap() == 0),
        _ => original["event"] == wake["event"],
    };
    if !matches {
        return Err("run occurrence differs from its immutable schedule".to_owned());
    }
    let r = &run["result"];
    let dispatch = r["dispatch_at_ms"].as_u64().unwrap_or(0);
    Ok(model::Run {
        id: OpId::parse(run["id"].as_str().unwrap()).unwrap(),
        loop_id: OpId::parse(run["loop_id"].as_str().unwrap()).unwrap(),
        definition_revision: model::NonEmpty::new(d.revision.clone()).unwrap(),
        wake: if wake["kind"] == "event" {
            model::Occurrence::Event {
                event: repository::event(wake["event"].as_str().unwrap()),
                event_id: model::NonEmpty::new(wake["event_id"].as_str().unwrap()).unwrap(),
            }
        } else {
            model::Occurrence::Scheduled {
                due_at_ms: wake["due_at_ms"].as_u64().unwrap(),
            }
        },
        started_at_ms: run["started_at_ms"].as_u64().unwrap(),
        updated_at_ms: run["updated_at_ms"].as_u64().unwrap(),
        priority: d.project(true).priority,
        result: match r["kind"].as_str().unwrap() {
            "checking" => model::RunResult::Checking,
            "quiet" => model::RunResult::Quiet,
            "check_failed" => model::RunResult::CheckFailed,
            "check_timed_out" => model::RunResult::CheckTimedOut,
            "shadow" => model::RunResult::Shadow,
            "deferred" => model::RunResult::Deferred,
            "dispatching" => model::RunResult::Dispatching {
                dispatch_at_ms: dispatch,
            },
            "created" => model::RunResult::Created {
                dispatch_at_ms: dispatch,
            },
            "not_created" => model::RunResult::NotCreated {
                dispatch_at_ms: dispatch,
            },
            "refused" => model::RunResult::Refused,
            _ => model::RunResult::Uncertain {
                dispatch_at_ms: dispatch,
            },
        },
    })
}

/// Independently observe persisted loop admissions and immutable check limits.
/// The caller binds the checkout/state to the service's trusted installation.
/// This reads only; no scheduler pass, switch or check is started.
pub fn observe(
    checkout: &std::path::Path,
    root: &std::path::Path,
    now_ms: u64,
) -> Result<Vec<crate::health::loops::Observation>, String> {
    let state = storage::read_snapshot(root)?;
    let repository = Repository(checkout.to_owned());
    let definitions = repository.current_for_observation()?;
    let observed = observations(
        &repository,
        &definitions,
        &state.runs,
        &state.enabled,
        now_ms,
    )?;
    // Also fence definitions/history changing while immutable blobs are read.
    let after = storage::read_snapshot(root)?;
    let current = repository.current_for_observation()?;
    if state != after
        || definitions
            .iter()
            .map(|d| &d.revision)
            .ne(current.iter().map(|d| &d.revision))
    {
        return Err("loop observation changed during projection".into());
    }
    Ok(observed)
}

fn observations(
    repository: &Repository,
    definitions: &[Definition],
    runs: &[Value],
    switches: &serde_json::Map<String, Value>,
    now_ms: u64,
) -> Result<Vec<crate::health::loops::Observation>, String> {
    use crate::health::loops::{Checking, Evidence, Observation};
    let projected = runs
        .iter()
        .map(|run| project_run(repository, run))
        .collect::<Result<Vec<_>, _>>()?;
    let mut snapshot = model::Snapshot {
        definitions: definitions
            .iter()
            .map(|d| {
                d.project(
                    switches
                        .get(d.value["id"].as_str().unwrap())
                        .and_then(Value::as_bool)
                        .unwrap_or(d.value["enabled"].as_bool().unwrap()),
                )
            })
            .collect(),
        runs: projected,
        active_agents: None,
    };
    // An off switch or removal never erases an already admitted check.
    // Include historical subjects so a terminal record can also positively
    // clear a previously stuck check after its definition is removed.
    let current = snapshot
        .definitions
        .iter()
        .map(|d| d.id.clone())
        .collect::<std::collections::BTreeSet<_>>();
    for run in runs {
        let id = OpId::parse(run["loop_id"].as_str().unwrap()).unwrap();
        if !snapshot.definitions.iter().any(|d| d.id == id) {
            let immutable = repository.blob(run["definition_revision"].as_str().unwrap())?;
            snapshot.definitions.push(immutable.project(false));
        }
    }
    // Zero capacities are a read-only planning device: every scheduled
    // proposal remains held, exposing its original due time without admission.
    let zero = model::Capacity {
        max: 0,
        urgent_reserve: 0,
    };
    let plan = model::plan(
        &snapshot,
        now_ms,
        &Limits {
            checks: zero,
            agents: zero,
        },
    )
    .map_err(|_| "invalid loop observation".to_owned())?;
    let mut out = Vec::new();
    for d in &snapshot.definitions {
        let next = if d.enabled {
            plan.held.iter().find_map(|held| match &held.action {
                model::Action::Check {
                    loop_id,
                    occurrence: model::Occurrence::Scheduled { due_at_ms },
                    ..
                } if loop_id == &d.id => Some(*due_at_ms),
                _ => None,
            })
        } else {
            None
        };
        let mut checking = Vec::new();
        for run in runs
            .iter()
            .filter(|run| run["loop_id"] == d.id.as_str() && run["result"]["kind"] == "checking")
        {
            let immutable = repository.blob(run["definition_revision"].as_str().unwrap())?;
            checking.push(Checking {
                run_id: OpId::parse(run["id"].as_str().unwrap()).unwrap(),
                started_at_ms: run["started_at_ms"].as_u64().unwrap(),
                timeout_ms: NonZeroU64::new(
                    immutable.value["check"]["timeout_ms"].as_u64().unwrap(),
                )
                .unwrap(),
            });
        }
        out.push(Observation {
            loop_id: d.id.clone(),
            next_due_at_ms: if current.contains(&d.id) {
                Evidence::Known(next)
            } else {
                Evidence::Unknown
            },
            checking: Evidence::Known(checking),
            disabled_by_failures: Evidence::Unknown,
        });
    }
    Ok(out)
}
