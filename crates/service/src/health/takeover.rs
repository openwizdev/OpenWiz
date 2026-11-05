//! TK1: a saved exact-loop reservation, confirmed pause, then own tick restart.
use super::*;
use openwiz_adapter_cloudroom::loops::recorded_fleet_loop;
use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_core::{
    fleet::{fleets::FleetsSource, model::IssueState},
    source::SourceError,
};

#[derive(Clone, PartialEq, Eq)]
pub(super) struct Binding {
    pub spec: Number,
    pub thread: Id,
    pub loop_id: Id,
    pub record: String,
}
pub(super) fn rows(value: &Value) -> &[Value] {
    value
        .get("retired_loops")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}
pub(super) fn matches(row: &Value, binding: &Binding) -> bool {
    row["spec"] == binding.spec.get()
        && row["thread"] == binding.thread.as_str()
        && row["loop"] == binding.loop_id.as_str()
}
pub(super) fn active(value: &Value, binding: &Binding) -> bool {
    rows(value)
        .iter()
        .any(|r| matches(r, binding) && r["phase"] == "active")
}
/// Revalidate the configured repository's complete open specs and latest
/// ownership record. A live or foreign thread never authorizes retirement.
pub(super) fn binding(
    health: &Health,
    spec: Number,
    thread: &Id,
    until: Instant,
) -> Result<Binding, String> {
    let list = GitHubFleets::with_executor(health.github.clone())
        .issues(until)
        .map_err(|_| "takeover specs are unread")?;
    if list.cut_short
        || list.rows.iter().filter(|i| i.number == spec).count() != 1
        || !list
            .rows
            .iter()
            .any(|i| i.number == spec && i.state == IssueState::Open && i.sub_issues.total > 0)
    {
        return Err("takeover spec is not a unique verified open spec".into());
    }
    let comments = TickReads::with_executor(health.github.clone())
        .comments(spec, until)
        .map_err(|_| "takeover ownership records are unread")?;
    let (owner, record) = super::observe::ownership(health, spec, &comments, until)?
        .ok_or("takeover ownership record is absent")?;
    if &owner != thread {
        return Err("takeover ownership changed or is ambiguous".into());
    }
    let loop_id = recorded_fleet_loop(&record, thread)
        .map_err(|_| "takeover ownership changed or is ambiguous")?;
    let binding = Binding {
        spec,
        thread: thread.clone(),
        loop_id,
        record,
    };
    if rows(&health.snapshot()?)
        .iter()
        .any(|r| r["loop"] == binding.loop_id.as_str() && !matches(r, &binding))
    {
        return Err("takeover loop is already reserved for another binding".into());
    }
    match health.room.health_thread_owned(
        thread,
        &Id::parse(health.config["project"].as_str().unwrap()).unwrap(),
        until,
    ) {
        Ok(true) | Err(SourceError::NotFound { .. }) => Ok(binding),
        _ => Err("takeover thread is live, foreign or unread".into()),
    }
}
pub(super) fn reserve(value: &mut Value, binding: &Binding, now: u64) {
    if rows(value).iter().any(|row| matches(row, binding)) {
        return;
    }
    if value.get("retired_loops").is_none() {
        value["retired_loops"] = json!([]);
    }
    value["retired_loops"].as_array_mut().unwrap().push(json!({"owner":"service_tick","spec":binding.spec,"thread":binding.thread,"loop":binding.loop_id,"phase":"pause_pending","at":now}));
}
pub(super) fn prepare(health: &Health, saved: &Binding, until: Instant) -> Result<(), String> {
    if binding(health, saved.spec, &saved.thread, until)? != *saved {
        return Err("takeover ownership changed before pause".into());
    }
    health
        .room
        .pause_fleet_loop(&saved.record, &saved.thread, &health.repository(), until)
        .map_err(|_| "takeover pause is unconfirmed")?;
    // This durable phase is visible to the runtime before it starts any tick.
    health.change(|value| {
        let row = value["retired_loops"]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .find(|row| matches(row, saved))
            .ok_or("takeover reservation disappeared")?;
        if row["phase"] != "active" {
            row["phase"] = json!("paused");
        }
        Ok(())
    })?;
    if binding(health, saved.spec, &saved.thread, until)? != *saved {
        return Err("takeover ownership changed after pause".into());
    }
    Ok(())
}
