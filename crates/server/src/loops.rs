//! Local loop switches; trust is supplied by embedding, never an HTTP caller.
use crate::{LoopContext, LoopSwitchError, loop_configuration};
#[derive(Clone)]
pub struct Switching {
    pub context: LoopContext,
}

use crate::{
    SendHost, Shared, api,
    http::{Head, Reply},
    send,
};
use std::{net::TcpStream, time::Instant};
pub const OFF_ROUTE: &str = "/api/v1/loops/{name}/off";
pub const ON_ROUTE: &str = "/api/v1/loops/{name}/on";
/// The loops page's one read (#549).
pub const LIST_ROUTE: &str = "/api/v1/loops";

pub(crate) fn respond(
    head: &Head,
    stream: &mut TcpStream,
    shared: &Shared,
    (target, enabled): (&str, bool),
    host: &str,
    query: Option<&str>,
    deadline: Instant,
) -> Reply {
    if head.method != "POST" {
        let mut reply = api::error(405, "method_not_allowed", "only POST is allowed");
        reply.extra.push(("Allow", "POST".to_owned()));
        return reply;
    }
    let Some(site) = shared
        .config
        .allowed_host
        .as_deref()
        .filter(|site| site.eq_ignore_ascii_case(host) && SendHost::new(site).is_ok())
    else {
        return api::error(
            421,
            "misdirected",
            "loop switches require the configured public host",
        );
    };
    if query.is_some() {
        return api::error(400, "invalid_request", "this route takes no query");
    }
    if let Some(reply) = send::cross_site(head, site, "a loop switch") {
        return reply;
    }
    let len = match send::length_within(head, 1024, "a loop switch") {
        Ok(len) => len as usize,
        Err(reply) => return reply,
    };
    let body = match send::read_body(stream, &head.rest, len, shared.config.limits.body_timeout) {
        Ok(body) => body,
        Err(reply) => return reply,
    };
    // Exactly an empty object. Identity, actor, time and scope are never
    // accepted from the client, including duplicate/unknown fields.
    if !serde_json::from_slice::<serde_json::Value>(&body)
        .ok()
        .and_then(|v| v.as_object().map(|o| o.is_empty()))
        .unwrap_or(false)
    {
        return api::error(
            400,
            "invalid_request",
            "a loop switch body must be an empty JSON object",
        );
    }
    let Some(switching) = &shared.loop_switches else {
        return api::error(
            503,
            "switch_unavailable",
            "trusted loop context is unavailable",
        );
    };
    if u64::try_from(shared.clock.now().0).is_err() {
        return api::error(503, "switch_unavailable", "loop clock precedes epoch");
    }
    match switching.context.switch_with_clock_until(
        target,
        enabled,
        shared.clock.as_ref(),
        deadline,
    ) {
        Ok(event) => api::ok(api::pretty(&event).unwrap()),
        Err(error @ LoopSwitchError::Busy) => {
            let mut reply = api::error(503, "switch_busy", &error.to_string());
            reply
                .extra
                .push(("Retry-After", crate::RETRY_AFTER_SECS.to_string()));
            reply
        }
        Err(LoopSwitchError::Refused(why)) => api::error(409, "switch_refused", &why),
    }
}

/// Explicit startup wiring for the installed service/server. Test entrypoints
/// keep supplying their own context. Missing install identity stays unavailable.
pub fn installed(state: &std::path::Path) -> Option<Switching> {
    let checkout = std::env::current_dir().ok()?;
    loop_configuration::installed(&checkout, state)
        .ok()
        .map(|context| Switching { context })
}

// ── The loops view (#549): `GET /api/v1/loops`, `openwiz.loops-view.v1` ──
// contracts/web-api.v1.md, "Loops view". Pure: definitions, run records and
// switch states already read and validated by the store, and the read time.

/// The cost window: 24 hours ending at the read.
pub const COST_WINDOW_MS: u64 = 86_400_000;

/// The view of `definitions` (loops.v1 definition documents) with their
/// `runs` (run records) and saved `switches`, read at `read_at_ms`.
pub fn view(
    definitions: &[serde_json::Value],
    runs: &[serde_json::Value],
    switches: &serde_json::Map<String, serde_json::Value>,
    read_at_ms: u64,
) -> serde_json::Value {
    use serde_json::{Value, json};
    let mut loops: Vec<Value> = definitions
        .iter()
        .map(|d| {
            let id = d["id"].as_str().unwrap_or_default();
            let mine: Vec<&Value> = runs.iter().filter(|r| r["loop_id"] == id).collect();
            let enabled = switches
                .get(id)
                .and_then(Value::as_bool)
                .or_else(|| d["enabled"].as_bool())
                .unwrap_or(false);
            let last = mine.iter().copied().max_by(|a, b| {
                let key = |r: &Value| (r["started_at_ms"].as_u64(), r["updated_at_ms"].as_u64());
                key(a)
                    .cmp(&key(b))
                    .then_with(|| a["id"].as_str().cmp(&b["id"].as_str()))
            });
            let last_run = last.map_or(Value::Null, |r| {
                json!({
                    "started_at_ms": r["started_at_ms"],
                    "updated_at_ms": r["updated_at_ms"],
                    "result": r["result"]["kind"],
                    "reason": r["result"].get("reason").cloned().unwrap_or(Value::Null),
                })
            });
            let problem = last
                .and_then(|r| r["result"]["kind"].as_str())
                .filter(|k| PROBLEMS.contains(k))
                .map_or(Value::Null, Value::from);
            json!({
                "id": d["id"], "name": d["name"], "owner": d["owner"], "mode": d["mode"],
                "enabled": enabled,
                "wake": d["wake"],
                "next_run": next_run(&d["wake"], enabled, &mine, read_at_ms),
                "last_run": last_run,
                "cost": cost(&mine, read_at_ms),
                "problem": problem,
            })
        })
        .collect();
    // Problems first; then by name (code points), then id. The page never re-sorts.
    loops.sort_by(|a, b| {
        a["problem"]
            .is_null()
            .cmp(&b["problem"].is_null())
            .then_with(|| a["name"].as_str().cmp(&b["name"].as_str()))
            .then_with(|| a["id"].as_str().cmp(&b["id"].as_str()))
    });
    json!({
        "schema": "openwiz.loops-view.v1",
        "read_at_ms": read_at_ms,
        "cost_window_ms": COST_WINDOW_MS,
        "loops": loops,
    })
}

/// `GET /api/v1/loops`, after the usual `GET` guards: the view, or
/// `503 loops_busy` (with `Retry-After`) or `503 loops_unavailable`.
pub(crate) fn read_route(shared: &Shared) -> Reply {
    let Some(switching) = &shared.loop_switches else {
        return api::error(
            503,
            "loops_unavailable",
            "trusted loop context is unavailable",
        );
    };
    let Ok(now_ms) = u64::try_from(shared.clock.now().0) else {
        return api::error(503, "loops_unavailable", "loop clock precedes epoch");
    };
    match read(&switching.context, now_ms, &std::time::Instant::now) {
        Ok(view) => api::ok(api::pretty(&view).unwrap()),
        Err(ReadError::Busy) => {
            let mut reply = api::error(
                503,
                "loops_busy",
                "a loop pass holds the loop state; nothing was read",
            );
            reply
                .extra
                .push(("Retry-After", crate::RETRY_AFTER_SECS.to_string()));
            reply
        }
        Err(ReadError::Unavailable(why)) => api::error(503, "loops_unavailable", &why),
    }
}

/// How long the read waits for a running scheduler pass before `loops_busy`.
pub const READ_LOCK_WAIT: std::time::Duration = std::time::Duration::from_secs(5);

/// Why the read answered no view: `loops_busy` (a pass held the state past
/// the wait; nothing read) or `loops_unavailable` (with its reason).
#[derive(Debug, PartialEq, Eq)]
pub enum ReadError {
    Busy,
    Unavailable(String),
}

/// The loops view from the trusted embedded context, read under the
/// scheduler's lock. Writes nothing: no state is created, no Git ref moved.
pub fn read(
    context: &LoopContext,
    read_at_ms: u64,
    monotonic: &dyn Fn() -> std::time::Instant,
) -> Result<serde_json::Value, ReadError> {
    let unavailable = |why: &str| ReadError::Unavailable(why.to_owned());
    let trust = context
        .trust
        .as_ref()
        .ok_or_else(|| unavailable("trusted loop context is unavailable"))?;
    if openwiz_core::fleet::starts::Repository::parse(&context.repository).is_err()
        || context.project.trim().is_empty()
        || !trust.verify(&context.checkout, &context.repository, &context.project)
    {
        return Err(unavailable(
            "loop repository or project identity is not verified",
        ));
    }
    // Opening creates missing state; a read never does, so it needs a pass first.
    let dir = context.state.join("service/loops");
    if !dir.join("run.lock").is_file() || !dir.join("enabled.json").is_file() {
        return Err(unavailable("the scheduler has not run a pass yet"));
    }
    let deadline = monotonic() + READ_LOCK_WAIT;
    let state = loop {
        match crate::loop_state::storage::Storage::open(&context.state) {
            Ok(state) => break state,
            Err(why) if why == STATE_HELD => {
                if monotonic() >= deadline {
                    return Err(ReadError::Busy);
                }
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
            Err(why) => return Err(ReadError::Unavailable(why)),
        }
    };
    let definitions = crate::loop_state::repository::Repository(context.checkout.clone())
        .current()
        .map_err(ReadError::Unavailable)?;
    let runs = state.runs().map_err(ReadError::Unavailable)?;
    // The store checks each run's schema; a run whose times run backwards is refused here too.
    if let Some(run) = runs
        .iter()
        .find(|r| r["updated_at_ms"].as_u64() < r["started_at_ms"].as_u64())
    {
        return Err(ReadError::Unavailable(format!(
            "loop run {} was updated before it started",
            run["id"].as_str().unwrap_or("?")
        )));
    }
    // As the planner validates: a scheduled run is admitted at or after its occurrence is due.
    if let Some(run) = runs.iter().find(|r| {
        r["wake"]["due_at_ms"]
            .as_u64()
            .is_some_and(|due| r["started_at_ms"].as_u64().is_none_or(|at| at < due))
    }) {
        return Err(ReadError::Unavailable(format!(
            "loop run {} was admitted before it was due",
            run["id"].as_str().unwrap_or("?")
        )));
    }
    let switches = state.switches().map_err(ReadError::Unavailable)?;
    drop(state);
    let definitions: Vec<_> = definitions.into_iter().map(|d| d.value).collect();
    Ok(view(&definitions, &runs, &switches, read_at_ms))
}

/// The store's answer when another pass owns the state (`Storage::open`).
const STATE_HELD: &str = "another loop pass owns the state";

/// A last run with one of these results is a problem on the page.
const PROBLEMS: [&str; 5] = [
    "check_failed",
    "check_timed_out",
    "not_created",
    "refused",
    "uncertain",
];

/// When the scheduler next checks the loop: L2's rule (`next_scheduled` in
/// `crates/core/src/loops/planner.rs`), where a run covers its occurrence's due
/// time through its start, so a late admission covers what it skipped.
fn next_run(
    wake: &serde_json::Value,
    enabled: bool,
    runs: &[&serde_json::Value],
    read_at_ms: u64,
) -> serde_json::Value {
    use serde_json::json;
    if !enabled {
        return json!({"kind": "none", "why": "off"});
    }
    let mut covered: Vec<(u64, u64)> = runs
        .iter()
        .filter_map(|r| {
            Some((
                r["wake"]["due_at_ms"].as_u64()?,
                r["started_at_ms"].as_u64()?,
            ))
        })
        .collect();
    covered.sort_unstable();
    let at = match wake["kind"].as_str() {
        Some("event") => return json!({"kind": "event", "event": wake["event"]}),
        Some("once") => wake["at_ms"]
            .as_u64()
            .filter(|at| !covered.iter().any(|(due, _)| due == at)),
        Some("interval") => (|| {
            let every = wake["every_ms"].as_u64().filter(|e| *e > 0)?;
            let anchor = wake["anchor_ms"].as_u64()?;
            let mut due = anchor;
            for &(from, through) in &covered {
                if from > due {
                    break;
                }
                if through >= due {
                    due = through.checked_add(every - (through - anchor) % every)?;
                }
            }
            Some(due)
        })(),
        _ => None,
    };
    match at {
        Some(at) if at > read_at_ms => json!({"kind": "at", "at_ms": at}),
        Some(at) => json!({"kind": "due", "at_ms": at}),
        None => json!({"kind": "none", "why": "done"}),
    }
}

/// The known sum over the cost window, or unknown when any run in it is.
fn cost(runs: &[&serde_json::Value], read_at_ms: u64) -> serde_json::Value {
    use serde_json::json;
    // (read - window, read]: `read - at < window`, so no subtraction saturates at the epoch.
    let window: Vec<_> = runs
        .iter()
        .filter(|r| {
            r["started_at_ms"]
                .as_u64()
                .is_some_and(|at| at <= read_at_ms && read_at_ms - at < COST_WINDOW_MS)
        })
        .collect();
    let known: Vec<u64> = window
        .iter()
        .filter(|r| r["cost"]["kind"] == "known")
        .filter_map(|r| r["cost"]["usd_micros"].as_u64())
        .collect();
    let missing = window.len() - known.len();
    match known.iter().try_fold(0u64, |sum, c| sum.checked_add(*c)) {
        Some(sum) if missing == 0 => json!({"kind": "known", "usd_micros": sum}),
        Some(_) => {
            json!({"kind": "unknown", "reason": format!("{missing} of {} runs in the window did not report cost.", window.len())})
        }
        None => json!({"kind": "unknown", "reason": "The cost sum is too large to report."}),
    }
}

#[cfg(test)]
mod view_tests {
    use super::{COST_WINDOW_MS, view};
    use serde_json::{Map, Value, json};

    const READ: u64 = 1_893_456_300_000;
    const TEN_MIN: u64 = 600_000;

    fn def(id: &str, name: &str, wake: Value, enabled: bool) -> Value {
        json!({"id": id, "name": name, "owner": "synthetic-owner", "mode": "active", "enabled": enabled, "wake": wake})
    }
    fn every_ten(anchor: u64) -> Value {
        json!({"kind": "interval", "every_ms": TEN_MIN, "anchor_ms": anchor})
    }
    fn run(id: &str, loop_id: &str, due: u64, started: u64, result: Value, cost: Value) -> Value {
        json!({"id": id, "loop_id": loop_id, "wake": {"kind": "interval", "due_at_ms": due},
               "started_at_ms": started, "updated_at_ms": started + 3_000, "result": result, "cost": cost})
    }
    fn usd(micros: u64) -> Value {
        json!({"kind": "known", "usd_micros": micros})
    }
    fn loops(v: &Value) -> &Vec<Value> {
        v["loops"].as_array().expect("a loops array")
    }
    fn one<'a>(v: &'a Value, id: &str) -> &'a Value {
        loops(v)
            .iter()
            .find(|l| l["id"] == id)
            .expect("the loop is listed")
    }

    #[test]
    fn lp6_view_lists_every_loop_problems_first_then_by_name() {
        let defs = [
            def("b-quiet", "Beta", every_ten(0), true),
            def("a-fail", "Zeta", every_ten(0), true),
            def("c-new", "Alpha", every_ten(0), true),
            def("d-same", "Alpha", every_ten(0), true),
        ];
        let runs = [
            run(
                "r1",
                "b-quiet",
                1_893_456_000_000,
                1_893_456_060_000,
                json!({"kind": "quiet"}),
                usd(0),
            ),
            run(
                "r2",
                "a-fail",
                1_893_456_000_000,
                1_893_456_060_000,
                json!({"kind": "check_failed", "reason": "Check could not complete successfully with valid UTF-8 output."}),
                usd(0),
            ),
            run(
                "r9",
                "gone-loop",
                1_893_456_000_000,
                1_893_456_060_000,
                json!({"kind": "quiet"}),
                usd(5),
            ),
        ];
        let v = view(&defs, &runs, &Map::new(), READ);
        assert_eq!(v["schema"], "openwiz.loops-view.v1");
        assert_eq!(v["read_at_ms"], READ);
        assert_eq!(v["cost_window_ms"], COST_WINDOW_MS);
        let ids: Vec<_> = loops(&v)
            .iter()
            .map(|l| l["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids, ["a-fail", "c-new", "d-same", "b-quiet"]);
        let failed = one(&v, "a-fail");
        assert_eq!(failed["problem"], "check_failed");
        assert_eq!(
            failed["last_run"],
            json!({"started_at_ms": 1_893_456_060_000u64, "updated_at_ms": 1_893_456_063_000u64,
            "result": "check_failed", "reason": "Check could not complete successfully with valid UTF-8 output."})
        );
        let keys: Vec<_> = failed
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        assert_eq!(keys.len(), 10, "{keys:?}");
        for k in [
            "id", "name", "owner", "mode", "enabled", "wake", "next_run", "last_run", "cost",
            "problem",
        ] {
            assert!(keys.contains(&k), "{k} missing");
        }
        assert_eq!(one(&v, "c-new")["last_run"], Value::Null);
        assert_eq!(one(&v, "b-quiet")["problem"], Value::Null);
        assert!(
            !v.to_string().contains("gone-loop"),
            "runs of no current definition are not shown"
        );
    }

    #[test]
    fn lp6_view_next_run_follows_the_planner() {
        let defs = [
            def("on-time", "On time", every_ten(1_893_456_000_000), true),
            def("late", "Late", every_ten(1_893_455_400_000), true),
            def("overdue", "Overdue", every_ten(1_893_456_000_000), true),
            def("off", "Off", every_ten(0), true),
            def(
                "once-ahead",
                "Once ahead",
                json!({"kind": "once", "at_ms": 1_893_460_000_000u64}),
                true,
            ),
            def(
                "once-done",
                "Once done",
                json!({"kind": "once", "at_ms": 1_893_450_000_000u64}),
                true,
            ),
            def(
                "on-event",
                "On event",
                json!({"kind": "event", "event": "github.pull_request_review"}),
                true,
            ),
        ];
        let mut done = run(
            "r3",
            "once-done",
            1_893_450_000_000,
            1_893_450_001_000,
            json!({"kind": "quiet"}),
            usd(0),
        );
        done["wake"] = json!({"kind": "once", "due_at_ms": 1_893_450_000_000u64});
        let runs = [
            run(
                "r1",
                "on-time",
                1_893_456_000_000,
                1_893_456_060_000,
                json!({"kind": "quiet"}),
                usd(0),
            ),
            // Admitted late: due 09:10, started 09:21, so it covers 09:10 to 09:21.
            run(
                "r2",
                "late",
                1_893_455_400_000,
                1_893_456_060_000,
                json!({"kind": "quiet"}),
                usd(0),
            ),
            done,
        ];
        let mut switches = Map::new();
        switches.insert("off".into(), json!(false));
        let v = view(&defs, &runs, &switches, READ);
        assert_eq!(
            one(&v, "on-time")["next_run"],
            json!({"kind": "at", "at_ms": 1_893_456_600_000u64})
        );
        assert_eq!(
            one(&v, "late")["next_run"],
            json!({"kind": "at", "at_ms": 1_893_456_600_000u64})
        );
        assert_eq!(
            one(&v, "overdue")["next_run"],
            json!({"kind": "due", "at_ms": 1_893_456_000_000u64})
        );
        assert_eq!(
            one(&v, "off")["next_run"],
            json!({"kind": "none", "why": "off"})
        );
        assert_eq!(one(&v, "off")["enabled"], false);
        assert_eq!(
            one(&v, "once-ahead")["next_run"],
            json!({"kind": "at", "at_ms": 1_893_460_000_000u64})
        );
        assert_eq!(
            one(&v, "once-done")["next_run"],
            json!({"kind": "none", "why": "done"})
        );
        assert_eq!(
            one(&v, "on-event")["next_run"],
            json!({"kind": "event", "event": "github.pull_request_review"})
        );
    }

    #[test]
    fn lp6_view_switch_state_overrides_the_definition() {
        let defs = [
            def("was-off", "Was off", every_ten(0), false),
            def("still-off", "Still off", every_ten(0), false),
        ];
        let mut switches = Map::new();
        switches.insert("was-off".into(), json!(true));
        let v = view(&defs, &[], &switches, READ);
        assert_eq!(one(&v, "was-off")["enabled"], true);
        assert_eq!(one(&v, "still-off")["enabled"], false);
        assert_eq!(
            one(&v, "still-off")["next_run"],
            json!({"kind": "none", "why": "off"})
        );
    }

    #[test]
    fn lp6_view_cost_is_the_last_24_hours_known_or_unknown() {
        let defs = [
            def("known", "Known", every_ten(0), true),
            def("unknown", "Unknown", every_ten(0), true),
            def("none", "None", every_ten(0), true),
        ];
        let quiet = json!({"kind": "quiet"});
        let runs = [
            run(
                "k1",
                "known",
                1_893_456_000_000,
                READ,
                quiet.clone(),
                usd(120_000),
            ),
            run(
                "k2",
                "known",
                1_893_400_000_000,
                READ - COST_WINDOW_MS + 1,
                quiet.clone(),
                usd(300_000),
            ),
            run(
                "k3",
                "known",
                1_893_300_000_000,
                READ - COST_WINDOW_MS,
                quiet.clone(),
                usd(9_000_000),
            ),
            run(
                "u1",
                "unknown",
                1_893_456_000_000,
                1_893_456_060_000,
                quiet.clone(),
                usd(10),
            ),
            run(
                "u2",
                "unknown",
                1_893_455_400_000,
                1_893_455_460_000,
                quiet.clone(),
                json!({"kind": "unknown", "reason": "Not reported."}),
            ),
            run(
                "u3",
                "unknown",
                1_893_454_800_000,
                1_893_454_860_000,
                quiet,
                usd(20),
            ),
        ];
        let v = view(&defs, &runs, &Map::new(), READ);
        assert_eq!(one(&v, "known")["cost"], usd(420_000));
        assert_eq!(
            one(&v, "unknown")["cost"],
            json!({"kind": "unknown", "reason": "1 of 3 runs in the window did not report cost."})
        );
        assert_eq!(one(&v, "none")["cost"], usd(0));
        // The window is (read - 24 h, read]: a run at the epoch counts at a read 1 ms later (review 1, R7).
        let defs = [def("early", "Early", every_ten(0), true)];
        let runs = [run("e1", "early", 0, 0, json!({"kind": "quiet"}), usd(5))];
        assert_eq!(
            one(&view(&defs, &runs, &Map::new(), 1), "early")["cost"],
            usd(5)
        );
    }

    #[test]
    fn lp6_view_last_run_and_problem() {
        let kinds = [
            ("quiet", json!({"kind": "quiet"}), Value::Null, Value::Null),
            (
                "deferred",
                json!({"kind": "deferred", "finding": "SECRET-FINDING", "reason": "Awaiting dispatch admission."}),
                json!("Awaiting dispatch admission."),
                Value::Null,
            ),
            (
                "timed",
                json!({"kind": "check_timed_out"}),
                Value::Null,
                json!("check_timed_out"),
            ),
            (
                "refused",
                json!({"kind": "refused", "finding": "SECRET-FINDING", "reason": "Budget refused."}),
                json!("Budget refused."),
                json!("refused"),
            ),
            (
                "uncertain",
                json!({"kind": "uncertain", "finding": "SECRET-FINDING", "op_id": "syn-op-1", "dispatch_at_ms": 1_893_456_061_000u64, "reason": "Outcome not confirmed."}),
                json!("Outcome not confirmed."),
                json!("uncertain"),
            ),
            (
                "not-created",
                json!({"kind": "not_created", "finding": "SECRET-FINDING", "op_id": "syn-op-2", "dispatch_at_ms": 1_893_456_061_000u64, "reason": "Refused by the gate."}),
                json!("Refused by the gate."),
                json!("not_created"),
            ),
            (
                "created",
                json!({"kind": "created", "finding": "SECRET-FINDING", "op_id": "syn-op-3", "dispatch_at_ms": 1_893_456_061_000u64, "thread_id": "thr_syn_0001"}),
                Value::Null,
                Value::Null,
            ),
        ];
        let defs: Vec<_> = kinds
            .iter()
            .map(|(id, ..)| def(id, id, every_ten(0), true))
            .collect();
        let runs: Vec<_> = kinds
            .iter()
            .map(|(id, result, ..)| {
                run(
                    &format!("r-{id}"),
                    id,
                    1_893_456_000_000,
                    1_893_456_060_000,
                    result.clone(),
                    usd(0),
                )
            })
            .collect();
        let v = view(&defs, &runs, &Map::new(), READ);
        for (id, result, reason, problem) in &kinds {
            let l = one(&v, id);
            assert_eq!(l["last_run"]["result"], result["kind"], "{id}");
            assert_eq!(l["last_run"]["reason"], *reason, "{id}");
            assert_eq!(l["problem"], *problem, "{id}");
        }
        let text = v.to_string();
        for leak in ["SECRET-FINDING", "syn-op-", "thr_syn_0001"] {
            assert!(!text.contains(leak), "{leak} leaked");
        }
        // The latest: greatest started_at_ms, then updated_at_ms, then id.
        let defs = [def("pick", "Pick", every_ten(0), true)];
        let mut newer_update = run(
            "r-a",
            "pick",
            1_893_456_000_000,
            1_893_456_060_000,
            json!({"kind": "check_timed_out"}),
            usd(0),
        );
        newer_update["updated_at_ms"] = json!(1_893_456_090_000u64);
        let runs = [
            run(
                "r-z",
                "pick",
                1_893_455_400_000,
                1_893_455_460_000,
                json!({"kind": "quiet"}),
                usd(0),
            ),
            run(
                "r-b",
                "pick",
                1_893_456_000_000,
                1_893_456_060_000,
                json!({"kind": "quiet"}),
                usd(0),
            ),
            newer_update,
        ];
        let v = view(&defs, &runs, &Map::new(), READ);
        assert_eq!(one(&v, "pick")["last_run"]["result"], "check_timed_out");
    }
}
