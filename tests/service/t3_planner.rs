//! T3 (ClosedWiz#268): the health planner's table tests, C3 of spec #262,
//! red first. They test `openwiz_core::health::plan` through its public
//! interface. Every expected value is a literal, taken from
//! `contracts/service.v1.md`.
//!
//! - `checks`: every check, healthy (nothing due), broken (its fix), broken
//!   after two tries (one "Needs you") and fixed (quiet again); unknown and
//!   unread; gone subjects.
//! - `owned`: nothing outside OpenWiz's own loops and fleet threads is ever
//!   a subject or a fix.
//! - `contract`: the contract's worked examples, reproduced.
//!
//! Every plan in every test also goes through [`Run::pass`]'s checks: the
//! planner's part of the state, printed, passes `service.v1.schema.json`
//! (in every test but the combination sweep, [`Run::without_schema`]);
//! the rules S1, S2, S3 and S6 hold; each fix and "Needs you" names an
//! open incident (S7); and each fix's subject is one this pass saw as
//! OpenWiz's.
//!
//! **Fixtures only.** Fixture tests never prove live behaviour.

/// A value of the planner's, printed as JSON.
macro_rules! json_of {
    ($value:expr) => {
        serde_json::to_value($value).expect("prints as JSON")
    };
}

#[path = "../fleet/schema.rs"]
mod schema;

#[path = "t3_checks.rs"]
mod checks;
#[path = "t3_contract.rs"]
mod contract;
#[path = "t3_owned.rs"]
mod owned;

use std::collections::BTreeSet;
use std::num::NonZeroU64;
use std::sync::OnceLock;

use openwiz_core::health::model::{
    CloudRoomSeen, Fault, Fix, FleetThreadResult, Id, Incidents, Known, Listed, LoopResult,
    NonEmpty, Number, Outcome, Pass, Repository, Rules, Seen, SeenFleetThread, SeenLoop,
    TakeoverOutcome, ThreadSeen, Unread,
};
use openwiz_core::health::{is_openwiz_loop, plan};
use openwiz_core::messaging::OpId;
use openwiz_core::model::Timestamp;
use serde_json::{Value, json};

pub const SCHEMA_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../contracts/service.v1.schema.json"
);
pub const CONTRACT_PATH: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts/service.v1.md");

/// OpenWiz's loop in the healthy service: the contract's example loop.
pub const LOOP_ID: &str = "loop_syn_0001";
pub const LOOP_NAME: &str = "launch-fleet synthetic-owner/synthetic-repo";
/// The healthy service's one fleet thread: spec #900's, as its records name
/// it.
pub const SPEC: u64 = 900;
pub const THREAD: &str = "thr_syn_0201";
/// The fleet thread a takeover starts.
pub const NEW_THREAD: &str = "thr_syn_0202";
/// The tick's schedule, `tick.every_s`, as in the contract's config.
pub const TICK_EVERY_S: u64 = 300;

/// A minute: one health pass, as in the contract's config.
pub const MINUTE: i64 = 60_000;
/// An hour: how long a subject stays healthy before its incident ends.
pub const HOUR: i64 = 3_600_000;
/// The first pass of each table.
pub const T0: i64 = 1_767_229_200_000;

pub fn id(text: &str) -> Id {
    Id::parse(text).expect("a valid id")
}

pub fn number(n: u64) -> Number {
    NonZeroU64::new(n).expect("1 or more")
}

pub fn text(words: &str) -> NonEmpty {
    NonEmpty::new(words).expect("not empty")
}

pub fn repository() -> Repository {
    Repository::parse("synthetic-owner", "synthetic-repo").expect("a valid repository")
}

pub fn rules() -> Rules {
    Rules {
        repository: repository(),
        tick_every_s: number(TICK_EVERY_S),
    }
}

pub fn seen_loop(id_text: &str, name: &str, paused: bool) -> SeenLoop {
    SeenLoop {
        id: id(id_text),
        name: name.to_owned(),
        paused,
    }
}

pub fn seen_thread(spec: u64, thread: &str, seen: ThreadSeen) -> SeenFleetThread {
    SeenFleetThread {
        spec: number(spec),
        thread: id(thread),
        seen,
    }
}

pub fn unread(gap: openwiz_core::health::model::Gap, reason: &str) -> Unread {
    Unread {
        gap,
        reason: text(reason),
    }
}

/// The healthy service: CloudRoom running, OpenWiz's one loop active, no
/// tick run going, spec #900's fleet thread there, and the server answering.
pub fn healthy() -> Seen {
    Seen {
        cloudroom: CloudRoomSeen::Running,
        loops: Listed::Read(vec![seen_loop(LOOP_ID, LOOP_NAME, false)]),
        tick_running_since: None,
        fleet_threads: Listed::Read(vec![seen_thread(SPEC, THREAD, ThreadSeen::Present)]),
        server: Known::Healthy,
    }
}

/// The healthy service's results, in the contract's order.
pub fn healthy_results() -> Value {
    json!([
        {"check": "cloudroom", "observed": {"state": "healthy"}},
        {"check": "loop", "loop": {"id": "loop_syn_0001", "name": "launch-fleet synthetic-owner/synthetic-repo"}, "observed": {"state": "healthy"}},
        {"check": "tick", "observed": {"state": "healthy"}},
        {"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201", "observed": {"state": "healthy"}},
        {"check": "server", "observed": {"state": "healthy"}}
    ])
}

/// The service schema, read once.
pub fn load_schema() -> &'static Value {
    static SCHEMA: OnceLock<Value> = OnceLock::new();
    SCHEMA.get_or_init(|| {
        let text = std::fs::read_to_string(SCHEMA_PATH).expect("the service schema is readable");
        serde_json::from_str(&text).expect("the service schema is JSON")
    })
}

pub fn contract_text() -> String {
    std::fs::read_to_string(CONTRACT_PATH).expect("the service contract is readable")
}

/// A run of health passes: the incidents carried from pass to pass, as the
/// service's state would carry them, and the executor's part, played by
/// the test (saving each try's outcome).
pub struct Run {
    pub incidents: Incidents,
    pub rules: Rules,
    ops: u32,
    /// `None`: the schema check is skipped (only the combination sweep).
    schema: Option<&'static Value>,
}

impl Default for Run {
    fn default() -> Self {
        Self::from(Incidents::default())
    }
}

impl From<Incidents> for Run {
    fn from(incidents: Incidents) -> Self {
        Self {
            incidents,
            rules: rules(),
            ops: 0,
            schema: Some(load_schema()),
        }
    }
}

impl Run {
    /// One pass at `at`. Checks the plan (the module's documentation), then
    /// keeps its incidents for the next pass.
    pub fn pass(&mut self, seen: &Seen, at: i64) -> Pass {
        let mut ops = self.ops;
        let mut new_op_id = || {
            ops += 1;
            OpId::parse(&format!("op-needs-you-{ops}")).expect("a valid op id")
        };
        let planned = plan(
            &self.incidents,
            seen,
            &self.rules,
            Timestamp(at),
            &mut new_op_id,
        );
        self.ops = ops;
        assert_eq!(planned.pass.at, Timestamp(at), "the pass is at its time");
        self.check_schema(&planned.pass, &planned.incidents);
        check_names_open(&planned.pass, &planned.incidents);
        check_rules(&planned.pass, &planned.incidents, at);
        check_subjects_seen(&planned.pass, seen, &self.rules);
        self.incidents = planned.incidents;
        planned.pass
    }

    /// The same run, without the schema check: for the combination sweep,
    /// whose 1,024 passes it would slow to seconds. Every other test
    /// checks each shape against the schema.
    pub fn without_schema(mut self) -> Self {
        self.schema = None;
        self
    }

    fn check_schema(&self, pass: &Pass, incidents: &Incidents) {
        let Some(schema_value) = self.schema else {
            return;
        };
        let state = json!({
            "schema": "openwiz.service-state.v1",
            "next_incident": json_of!(&incidents.next_incident),
            "tick": {"running": null, "last_ended": null},
            "last_pass": json_of!(pass),
            "incidents": json_of!(&incidents.incidents),
            "update": null
        });
        let errors = schema::validate(schema_value, &state);
        assert!(
            errors.is_empty(),
            "the plan, in a state, breaks the schema: {errors:#?}\n{state:#}"
        );
    }

    /// The executor's part: saves `outcome` as each running try's outcome.
    /// A takeover that is done names [`NEW_THREAD`].
    pub fn settle(&mut self, outcome: &Outcome) {
        for incident in &mut self.incidents.incidents {
            match &mut incident.fault {
                Fault::Loop { tries, .. }
                | Fault::Tick { tries, .. }
                | Fault::Server { tries, .. } => {
                    if let Some(last) = tries.last_mut()
                        && last.outcome.is_none()
                    {
                        last.outcome = Some(outcome.clone());
                    }
                }
                Fault::FleetThread { tries, .. } => {
                    if let Some(last) = tries.last_mut()
                        && last.outcome.is_none()
                    {
                        last.outcome = Some(match outcome {
                            Outcome::Done => TakeoverOutcome::Done {
                                thread: id(NEW_THREAD),
                            },
                            Outcome::Failed { gap, reason } => TakeoverOutcome::Failed {
                                gap: *gap,
                                reason: reason.clone(),
                            },
                            Outcome::Interrupted => TakeoverOutcome::Interrupted,
                        });
                    }
                }
                Fault::CloudRoom { .. } => {}
            }
        }
    }

    /// The incidents, printed.
    pub fn incidents_json(&self) -> Value {
        json_of!(&self.incidents.incidents)
    }
}

/// S1: one result for each subject in a pass, one each for `tick`,
/// `server` and `cloudroom`, and an `unread` check has no other result.
/// S2: incident ids are distinct, each below `next_incident`, and a subject
/// has at most one. S3 and S6: a second try only after a first, and every
/// time in an incident between its `opened_at` and the pass.
fn check_rules(pass: &Pass, incidents: &Incidents, at: i64) {
    let subject = |value: &Value| {
        let field = value
            .get("loop")
            .map(|l| l["id"].clone())
            .or_else(|| value.get("spec").cloned());
        (
            value["check"].as_str().unwrap().to_owned(),
            field.unwrap_or(Value::Null).to_string(),
        )
    };
    let results = json_of!(&pass.results);
    let mut subjects = BTreeSet::new();
    let mut unread = BTreeSet::new();
    for result in results.as_array().unwrap() {
        if result.get("unread").is_some() {
            assert!(
                unread.insert(result["check"].as_str().unwrap().to_owned()),
                "S1: two unread {result}"
            );
        } else {
            assert!(
                subjects.insert(subject(result)),
                "S1: two results for one subject: {result}"
            );
        }
    }
    for check in &unread {
        assert!(
            subjects.iter().all(|(c, _)| c != check),
            "S1: an unread {check} beside its subjects' results: {results}"
        );
    }
    for check in ["cloudroom", "tick", "server"] {
        let count = results
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| r["check"] == check)
            .count();
        assert_eq!(count, 1, "S1: one {check} result: {results}");
    }

    let open = json_of!(&incidents.incidents);
    let next = incidents.next_incident.get();
    let mut ids = BTreeSet::new();
    let mut subjects = BTreeSet::new();
    for incident in open.as_array().unwrap() {
        let id = incident["id"].as_str().unwrap();
        let number: u64 = id.strip_prefix('i').unwrap().parse().unwrap();
        assert!(number < next, "S2: {id} isn't below next_incident {next}");
        assert!(ids.insert(id.to_owned()), "S2: two incidents {id}");
        assert!(
            subjects.insert(subject(incident)),
            "S2: two incidents for one subject: {open}"
        );
        let opened = incident["opened_at"].as_i64().unwrap();
        assert!(opened <= at, "S6: {id} opened after the pass");
        let within = |value: &Value, what: &str| {
            if let Some(time) = value.as_i64() {
                assert!(
                    opened <= time && time <= at,
                    "S3, S6: {id}'s {what} {time} is outside {opened}..{at}"
                );
            }
        };
        within(&incident["healthy_since"], "healthy_since");
        within(&incident["needs_you"]["at"], "Needs you");
        if let Some(tries) = incident.get("tries") {
            within(&tries["first"]["at"], "first try");
            within(&tries["second"]["at"], "second try");
            if !tries["second"].is_null() {
                assert!(
                    !tries["first"].is_null(),
                    "S3: {id}'s second try without a first"
                );
                assert!(
                    tries["first"]["at"].as_i64() <= tries["second"]["at"].as_i64(),
                    "S3: {id}'s tries out of order"
                );
            }
        }
    }
}

/// S7: each fix and each "Needs you" of a pass names an open incident.
fn check_names_open(pass: &Pass, incidents: &Incidents) {
    let open: Vec<_> = incidents.incidents.iter().map(|i| i.id).collect();
    for fix in &pass.fixes {
        let incident = match fix {
            Fix::ResumeLoop { incident, .. }
            | Fix::RestartTick { incident, .. }
            | Fix::TakeOverFleetThread { incident, .. }
            | Fix::RestartServer { incident, .. } => incident,
        };
        assert!(
            open.contains(incident),
            "fix {fix:?} names no open incident"
        );
    }
    for incident in &pass.needs_you {
        assert!(
            open.contains(incident),
            "a Needs you for {incident}, which isn't open"
        );
    }
}

/// Every fix's subject is one this pass saw as OpenWiz's: a loop in the
/// loop list whose name is OpenWiz's, or a fleet thread its spec's records
/// name. And every loop in a result is one of OpenWiz's.
fn check_subjects_seen(pass: &Pass, seen: &Seen, rules: &Rules) {
    let ours = |loop_id: &Id, name: &NonEmpty| match &seen.loops {
        Listed::Read(loops) => loops.iter().any(|l| {
            &l.id == loop_id
                && l.name == name.as_str()
                && is_openwiz_loop(&l.name, &rules.repository)
        }),
        Listed::Unread(_) => false,
    };
    for fix in &pass.fixes {
        match fix {
            Fix::ResumeLoop { subject, .. } => assert!(
                ours(&subject.id, &subject.name),
                "resume_loop for a loop this pass didn't see as OpenWiz's: {fix:?}"
            ),
            Fix::TakeOverFleetThread { spec, thread, .. } => {
                let named = match &seen.fleet_threads {
                    Listed::Read(threads) => threads
                        .iter()
                        .any(|t| &t.spec == spec && &t.thread == thread),
                    Listed::Unread(_) => false,
                };
                assert!(
                    named,
                    "a takeover of a thread no open spec's records name: {fix:?}"
                );
            }
            Fix::RestartTick { .. } | Fix::RestartServer { .. } => {}
        }
    }
    for result in &pass.results {
        if let openwiz_core::health::model::CheckResult::Loop(LoopResult::Seen {
            subject, ..
        }) = result
        {
            assert!(
                ours(&subject.id, &subject.name),
                "a result for a loop that isn't OpenWiz's: {result:?}"
            );
        }
        if let openwiz_core::health::model::CheckResult::FleetThread(FleetThreadResult::Seen {
            spec,
            thread,
            ..
        }) = result
        {
            let named = match &seen.fleet_threads {
                Listed::Read(threads) => threads
                    .iter()
                    .any(|t| &t.spec == spec && &t.thread == thread),
                Listed::Unread(_) => false,
            };
            assert!(
                named,
                "a result for a thread no open spec's records name: {result:?}"
            );
        }
    }
}

/// The pass's fixes, printed.
pub fn fixes(pass: &Pass) -> Value {
    json_of!(&pass.fixes)
}

/// The pass's "Needs you" items, printed.
pub fn needs_you(pass: &Pass) -> Value {
    json_of!(&pass.needs_you)
}

/// The pass's results, printed.
pub fn results(pass: &Pass) -> Value {
    json_of!(&pass.results)
}

/// Asserts the pass made nothing due.
pub fn assert_nothing_due(pass: &Pass, at: &str) {
    assert_eq!(fixes(pass), json!([]), "{at}: no fix is due");
    assert_eq!(needs_you(pass), json!([]), "{at}: no Needs you is due");
}
