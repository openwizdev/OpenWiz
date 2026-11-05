//! Convert the already strict service-state document to the pure planner's types.
use openwiz_core::{health::model::*, messaging::OpId, model::Timestamp};
use serde_json::Value;
fn time(v: &Value) -> Result<Timestamp, String> {
    v.as_u64()
        .and_then(|n| i64::try_from(n).ok())
        .map(Timestamp)
        .ok_or_else(|| "health time is out of range".to_owned())
}
fn number(v: &Value) -> Number {
    Number::new(v.as_u64().expect("validated number")).expect("positive number")
}
fn text(v: &Value) -> &str {
    v.as_str().expect("validated string")
}
fn gap(v: &Value) -> Result<Gap, String> {
    Ok(match text(v) {
        "untested_version" => Gap::UntestedVersion,
        "command_failed" => Gap::CommandFailed,
        "timed_out" => Gap::TimedOut,
        "budget_exhausted" => Gap::BudgetExhausted,
        "malformed" => Gap::Malformed,
        "missing_field" => Gap::MissingField,
        "wrong_type" => Gap::WrongType,
        "not_found" => Gap::NotFound,
        "cloudroom_not_running" => Gap::CloudroomNotRunning,
        _ => return Err("unknown health gap".into()),
    })
}
fn outcome(v: &Value) -> Result<Outcome, String> {
    Ok(match text(&v["state"]) {
        "done" => Outcome::Done,
        "interrupted" => Outcome::Interrupted,
        "failed" => Outcome::Failed {
            gap: gap(&v["gap"])?,
            reason: NonEmpty::new(text(&v["reason"])).unwrap(),
        },
        _ => return Err("unknown health outcome".into()),
    })
}
fn takeover(v: &Value) -> Result<TakeoverOutcome, String> {
    Ok(match text(&v["state"]) {
        "done" if v["owner"] == "service_tick" => TakeoverOutcome::ServiceTick {
            owner: ServiceTickOwner::ServiceTick,
            retired_loop: Id::parse(text(&v["retired_loop"])).unwrap(),
        },
        "done" => TakeoverOutcome::Done {
            thread: Id::parse(text(&v["thread"])).unwrap(),
        },
        "interrupted" => TakeoverOutcome::Interrupted,
        "failed" => TakeoverOutcome::Failed {
            gap: gap(&v["gap"])?,
            reason: NonEmpty::new(text(&v["reason"])).unwrap(),
        },
        _ => return Err("unknown takeover outcome".into()),
    })
}
fn saved<O>(v: &Value, read: fn(&Value) -> Result<O, String>) -> Result<SavedTry<O>, String> {
    Ok(SavedTry {
        at: time(&v["at"])?,
        outcome: if v["outcome"].is_null() {
            None
        } else {
            Some(read(&v["outcome"])?)
        },
        comment: (!v["comment"].is_null()).then(|| number(&v["comment"])),
    })
}
fn tries<O>(v: &Value, read: fn(&Value) -> Result<O, String>) -> Result<Tries<O>, String> {
    if v["first"].is_null() {
        return Ok(Tries::Zero);
    }
    let first = saved(&v["first"], read)?;
    Ok(if v["second"].is_null() {
        Tries::One(first)
    } else {
        Tries::Two(first, saved(&v["second"], read)?)
    })
}
pub fn incidents(value: &Value) -> Result<Incidents, String> {
    crate::document::read(crate::document::Document::State, &value.to_string())?;
    let incidents = value["incidents"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|v| v["check"] != "watchdog")
        .map(|v| {
            let fault = match text(&v["check"]) {
                "loop" => Fault::Loop {
                    subject: Loop {
                        id: Id::parse(text(&v["loop"]["id"])).unwrap(),
                        name: NonEmpty::new(text(&v["loop"]["name"])).unwrap(),
                    },
                    broken: LoopBroken::Paused,
                    tries: tries(&v["tries"], outcome)?,
                },
                "tick" => Fault::Tick {
                    broken: TickBroken::Stalled {
                        run_started_at: time(&v["broken"]["run_started_at"])?,
                    },
                    tries: tries(&v["tries"], outcome)?,
                },
                "server" => Fault::Server {
                    broken: match text(&v["broken"]["what"]) {
                        "refused" => ServerBroken::Refused,
                        "timed_out" => ServerBroken::TimedOut,
                        "wrong_answer" => ServerBroken::WrongAnswer,
                        _ => return Err("unknown server fault".into()),
                    },
                    tries: tries(&v["tries"], outcome)?,
                },
                "fleet_thread" => Fault::FleetThread {
                    spec: number(&v["spec"]),
                    thread: Id::parse(text(&v["thread"])).unwrap(),
                    broken: match text(&v["broken"]["what"]) {
                        "not_found" => FleetThreadBroken::NotFound,
                        "archived" => FleetThreadBroken::Archived,
                        _ => return Err("unknown fleet fault".into()),
                    },
                    tries: tries(&v["tries"], takeover)?,
                },
                "cloudroom" => Fault::CloudRoom {
                    broken: CloudRoomBroken::NotRunning,
                },
                _ => return Err("unknown health check".into()),
            };
            Ok(Incident {
                id: IncidentId(Number::new(text(&v["id"])[1..].parse().unwrap()).unwrap()),
                fault,
                opened_at: time(&v["opened_at"])?,
                healthy_since: if v["healthy_since"].is_null() {
                    None
                } else {
                    Some(time(&v["healthy_since"])?)
                },
                needs_you: if v["needs_you"].is_null() {
                    None
                } else {
                    let n = &v["needs_you"];
                    Some(NeedsYou {
                        at: time(&n["at"])?,
                        op_id: OpId::parse(text(&n["op_id"]))
                            .map_err(|_| "invalid saved notification id")?,
                        comment: (!n["comment"].is_null()).then(|| number(&n["comment"])),
                    })
                },
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    Ok(Incidents {
        next_incident: number(&value["next_incident"]),
        incidents,
    })
}
