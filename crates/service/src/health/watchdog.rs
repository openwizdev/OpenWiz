//! Independent loop observations, registered through the existing health job.
use super::{WatchdogRead, loops::Evidence};
use serde_json::Value;
use std::{path::Path, sync::Arc};
pub(super) fn installed(root: &Path, config: &Value) -> Arc<WatchdogRead> {
    let root = root.to_owned();
    let repository = format!(
        "{}/{}",
        config["repository"]["owner"].as_str().unwrap(),
        config["repository"]["name"].as_str().unwrap()
    );
    let project = config["project"].as_str().unwrap().to_owned();
    Arc::new(move |now| {
        let read = (|| {
            let checkout = std::env::current_dir().map_err(|_| "loop checkout unavailable")?;
            let context = openwiz_store::loops::config::installed(&checkout, &root)?;
            if context.repository != repository
                || context.project != project
                || !context
                    .trust
                    .as_ref()
                    .is_some_and(|t| t.verify(&checkout, &repository, &project))
            {
                return Err("loop installation identity is unavailable".into());
            }
            crate::loops::observe(&checkout, &root, now)
        })();
        match read {
            Ok(rows) => Evidence::Known(rows),
            Err(_) => Evidence::Unknown,
        }
    })
}

use super::loops::{self, Fault, Observation, Problem};
use openwiz_core::messaging::OpId;
use serde_json::json;
use std::num::NonZeroU64;

fn fault(value: &Value) -> Result<Fault, String> {
    let time = |key: &str| {
        value[key]
            .as_u64()
            .ok_or_else(|| "invalid saved watchdog time".to_owned())
    };
    Ok(match value["what"].as_str() {
        Some("missed") => Fault::Missed {
            due_at_ms: time("due_at_ms")?,
        },
        Some("stuck") => Fault::Stuck {
            run_id: OpId::parse(value["run_id"].as_str().ok_or("invalid watchdog run")?)
                .map_err(|_| "invalid watchdog run")?,
            started_at_ms: time("started_at_ms")?,
            timeout_ms: NonZeroU64::new(time("timeout_ms")?).ok_or("invalid watchdog limit")?,
        },
        Some("disabled_by_failures") => Fault::DisabledByFailures,
        _ => return Err("invalid saved watchdog fault".into()),
    })
}
fn problem(value: &Value) -> Result<Problem, String> {
    Ok(Problem {
        loop_id: OpId::parse(value["loop_id"].as_str().ok_or("invalid watchdog loop")?)
            .map_err(|_| "invalid watchdog loop")?,
        fault: fault(&value["broken"])?,
    })
}
fn broken(fault: &Fault) -> Value {
    match fault {
        Fault::Missed { due_at_ms } => {
            json!({"state":"broken","what":"missed","due_at_ms":due_at_ms})
        }
        Fault::Stuck {
            run_id,
            started_at_ms,
            timeout_ms,
        } => {
            json!({"state":"broken","what":"stuck","run_id":run_id,"started_at_ms":started_at_ms,"timeout_ms":timeout_ms.get()})
        }
        Fault::DisabledByFailures => json!({"state":"broken","what":"disabled_by_failures"}),
    }
}
/// Merge LP4 into the same durable health transaction. Notification intents
/// outlive open problems, so immediate recovery cannot lose an unsent item.
pub(super) fn apply(
    state: &mut Value,
    before: &Value,
    observations: Evidence<Vec<Observation>>,
    now: u64,
    new_id: &mut dyn FnMut() -> OpId,
) -> Result<(), String> {
    let old = before["incidents"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|i| i["check"] == "watchdog")
        .collect::<Vec<_>>();
    let problems = old
        .iter()
        .map(|i| problem(i))
        .collect::<Result<Vec<_>, _>>()?;
    let input = match &observations {
        Evidence::Known(rows) => Evidence::Known(rows.as_slice()),
        Evidence::Unknown => Evidence::Unknown,
    };
    let plan = loops::plan(input, &problems, now).map_err(|_| "invalid loop health observation")?;
    let mut deliveries = before
        .get("watchdog_deliveries")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    for open in &plan.open {
        let incident = if let Some(index) = problems.iter().position(|p| p == open) {
            old[index].clone()
        } else {
            let n = state["next_incident"].as_u64().unwrap();
            state["next_incident"] = json!(
                n.checked_add(1)
                    .ok_or("health incident counter exhausted")?
            );
            let incident = json!({"id":format!("i{n}"),"check":"watchdog","loop_id":open.loop_id,"broken":broken(&open.fault),"opened_at":now,"healthy_since":null,"needs_you":{"at":now,"op_id":new_id(),"comment":null}});
            state["last_pass"]["needs_you"]
                .as_array_mut()
                .unwrap()
                .push(incident["id"].clone());
            deliveries.push(incident.clone());
            incident
        };
        state["incidents"].as_array_mut().unwrap().push(incident);
    }
    state["watchdog_deliveries"] = json!(deliveries);
    let unknown = plan.unknown.iter().map(|u| json!({"loop_id":u.loop_id,"kind":match u.kind {loops::Kind::Missed=>"missed",loops::Kind::Stuck=>"stuck",loops::Kind::DisabledByFailures=>"disabled_by_failures"}})).collect::<Vec<_>>();
    state["last_pass"]["results"].as_array_mut().unwrap().push(json!({"check":"watchdog","open":plan.open.iter().map(|p|json!({"loop_id":p.loop_id,"broken":broken(&p.fault)})).collect::<Vec<_>>(),"unknown":unknown,"snapshot_unknown":plan.snapshot_unknown}));
    Ok(())
}
