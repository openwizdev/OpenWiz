//! The health planner (OpenWiz 0.0.8, T3, ClosedWiz#268): from what one
//! health pass saw of the service (its tick, its server, its loops, its
//! fleet threads and CloudRoom) and the incidents still open, the pass's
//! results, the fixes due and the "Needs you" items, by the rules of
//! `contracts/service.v1.md` ("The checks", "Incidents and the two-tries
//! rule"). Pure: no I/O, no clock and no randomness of its own. The time
//! is the caller's `now`, and each "Needs you"'s op id comes from the
//! caller's `new_op_id`, as op ids are made outside the core.
//!
//! [`model`] holds the types. [`plan`] is the planner, and
//! [`is_openwiz_loop`] the one rule for which loops are OpenWiz's.
//!
//! **Save before you act.** The plan's incidents already hold each due try
//! (its `outcome` `None`) and each due "Needs you" (its op id): the
//! executor (T5) saves them before it acts, saves each outcome once its
//! command returns, and turns a try still saved with no outcome into
//! [`model::Outcome::Interrupted`] at start.
//!
//! **Fail closed.** A loop is a subject only when its name is OpenWiz's; a
//! fleet thread only when an open spec's records name it. A list that names
//! one loop id or one spec twice can't give one result for each subject
//! (S1), so its check is `unread` (`malformed`): nothing is due from it,
//! and nothing of its ends.

pub mod model;

use std::collections::BTreeSet;
use std::num::NonZeroU64;

use model::{
    CheckResult, CloudRoomBroken, CloudRoomSeen, Fault, Fix, FleetThreadBroken, FleetThreadResult,
    Gap, Id, Incident, IncidentId, Incidents, Known, Listed, LoopBroken, LoopResult, NeedsYou,
    NonEmpty, Number, Observed, Pass, Plan, Repository, Rules, SavedTry, Seen, ThreadSeen,
    TickBroken, Tries, Try, Unread,
};

use crate::messaging::OpId;
use crate::model::Timestamp;

/// How long a subject stays healthy before its incident ends: an hour.
pub const HEALTHY_FOR_MS: i64 = 3_600_000;

/// The start every OpenWiz loop's name has: `launch-fleet` and a space.
const LOOP_PREFIX: &str = "launch-fleet ";

const LOOPS_CLOUDROOM_DOWN: &str = "CloudRoom is not running, so its loops can't be read";
const THREAD_CLOUDROOM_DOWN: &str = "CloudRoom is not running, so the thread can't be read";
const LOOP_ID_TWICE: &str = "room-cli loop list named one loop id twice";
const SPEC_TWICE: &str = "the open specs' records named one spec twice";

/// One health pass at `now`: works out each subject's result from `seen`,
/// then applies the two-tries rule to `before`'s incidents.
pub fn plan(
    before: &Incidents,
    seen: &Seen,
    rules: &Rules,
    now: Timestamp,
    new_op_id: &mut dyn FnMut() -> OpId,
) -> Plan {
    plan_with_retired(before, seen, rules, now, new_op_id, &[])
}

/// TK1: exact loop IDs with a saved takeover intent or retirement are never
/// resumed. Full-list ambiguity is still checked before subject filtering.
pub fn plan_with_retired(
    before: &Incidents,
    seen: &Seen,
    rules: &Rules,
    now: Timestamp,
    new_op_id: &mut dyn FnMut() -> OpId,
    retired: &[Id],
) -> Plan {
    let results = results(seen, rules, now, retired);
    let mut planner = Planner {
        now,
        next_incident: before.next_incident,
        incidents: before.incidents.clone(),
        fixes: Vec::new(),
        needs_you: Vec::new(),
        new_op_id,
    };
    for result in &results {
        planner.apply(result);
    }
    planner.end_gone(&results);
    Plan {
        pass: Pass {
            at: now,
            results,
            fixes: planner.fixes,
            needs_you: planner.needs_you,
        },
        incidents: Incidents {
            next_incident: planner.next_incident,
            incidents: planner.incidents,
        },
    }
}

/// Whether a loop named `name` is one of OpenWiz's: the name starts
/// `launch-fleet ` and, split at each space, has the repository
/// (`<owner>/<name>`) as one of its words, compared exactly.
pub fn is_openwiz_loop(name: &str, repository: &Repository) -> bool {
    let word = repository.to_string();
    name.starts_with(LOOP_PREFIX) && name.split(' ').any(|w| w == word)
}

/// Each subject's result, `cloudroom` first, in the contract's order:
/// `cloudroom`, `loop`, `tick`, `fleet_thread`, `server`.
fn results(seen: &Seen, rules: &Rules, now: Timestamp, retired: &[Id]) -> Vec<CheckResult> {
    let running = seen.cloudroom == CloudRoomSeen::Running;
    let mut results = vec![CheckResult::CloudRoom {
        observed: if running {
            Known::Healthy
        } else {
            Known::Broken(CloudRoomBroken::NotRunning)
        },
    }];

    match &seen.loops {
        _ if !running => results.push(CheckResult::Loop(LoopResult::Unread {
            unread: unread(Gap::CloudroomNotRunning, LOOPS_CLOUDROOM_DOWN),
        })),
        Listed::Unread(why) => results.push(CheckResult::Loop(LoopResult::Unread {
            unread: why.clone(),
        })),
        Listed::Read(loops) if twice(loops.iter().map(|l| &l.id)) => {
            results.push(CheckResult::Loop(LoopResult::Unread {
                unread: unread(Gap::Malformed, LOOP_ID_TWICE),
            }))
        }
        Listed::Read(loops) => results.extend(
            loops
                .iter()
                .filter(|l| is_openwiz_loop(&l.name, &rules.repository))
                .filter(|l| !retired.contains(&l.id))
                .filter_map(|l| {
                    Some(CheckResult::Loop(LoopResult::Seen {
                        subject: model::Loop {
                            id: l.id.clone(),
                            name: NonEmpty::new(l.name.clone())?,
                        },
                        observed: if l.paused {
                            Observed::Broken(LoopBroken::Paused)
                        } else {
                            Observed::Healthy
                        },
                    }))
                }),
        ),
    }

    results.push(CheckResult::Tick {
        observed: tick(seen.tick_running_since, rules.tick_every_s, now),
    });

    match &seen.fleet_threads {
        Listed::Unread(why) => results.push(CheckResult::FleetThread(FleetThreadResult::Unread {
            unread: why.clone(),
        })),
        Listed::Read(threads) if twice(threads.iter().map(|t| t.spec)) => {
            results.push(CheckResult::FleetThread(FleetThreadResult::Unread {
                unread: unread(Gap::Malformed, SPEC_TWICE),
            }))
        }
        Listed::Read(threads) => results.extend(threads.iter().map(|t| {
            CheckResult::FleetThread(FleetThreadResult::Seen {
                spec: t.spec,
                thread: t.thread.clone(),
                observed: match &t.seen {
                    _ if !running => {
                        Observed::Unknown(unread(Gap::CloudroomNotRunning, THREAD_CLOUDROOM_DOWN))
                    }
                    ThreadSeen::Present => Observed::Healthy,
                    ThreadSeen::NotFound => Observed::Broken(FleetThreadBroken::NotFound),
                    ThreadSeen::Archived => Observed::Broken(FleetThreadBroken::Archived),
                    ThreadSeen::Unknown(why) => Observed::Unknown(why.clone()),
                },
            })
        })),
    }

    results.push(CheckResult::Server {
        observed: seen.server,
    });
    results
}

/// The tick is stalled when a run is still going at its next run's time,
/// `every_s` after it started.
fn tick(
    running_since: Option<Timestamp>,
    every_s: NonZeroU64,
    now: Timestamp,
) -> Known<TickBroken> {
    let Some(started) = running_since else {
        return Known::Healthy;
    };
    let every_ms = i64::try_from(every_s.get())
        .ok()
        .and_then(|s| s.checked_mul(1000))
        .unwrap_or(i64::MAX);
    if now.0 >= started.0.saturating_add(every_ms) {
        Known::Broken(TickBroken::Stalled {
            run_started_at: started,
        })
    } else {
        Known::Healthy
    }
}

fn unread(gap: Gap, reason: &'static str) -> Unread {
    Unread {
        gap,
        reason: NonEmpty::new(reason).expect("OpenWiz's reasons are never empty"),
    }
}

/// Whether any item comes twice.
fn twice<T: Ord>(items: impl IntoIterator<Item = T>) -> bool {
    let mut seen = BTreeSet::new();
    items.into_iter().any(|item| !seen.insert(item))
}

/// Who an incident is about: one subject has at most one open incident.
#[derive(PartialEq, Eq)]
enum Subject<'a> {
    Loop(&'a Id),
    Tick,
    FleetThread(Number),
    Server,
    CloudRoom,
}

impl Fault {
    fn subject(&self) -> Subject<'_> {
        match self {
            Self::Loop { subject, .. } => Subject::Loop(&subject.id),
            Self::Tick { .. } => Subject::Tick,
            Self::FleetThread { spec, .. } => Subject::FleetThread(*spec),
            Self::Server { .. } => Subject::Server,
            Self::CloudRoom { .. } => Subject::CloudRoom,
        }
    }

    /// Takes `newer`'s broken observation and subject fields (a loop's
    /// name, the fleet thread last found gone), keeping the tries.
    fn refresh(&mut self, newer: Self) {
        match (self, newer) {
            (
                Self::Loop {
                    subject, broken, ..
                },
                Self::Loop {
                    subject: s,
                    broken: b,
                    ..
                },
            ) => {
                *subject = s;
                *broken = b;
            }
            (Self::Tick { broken, .. }, Self::Tick { broken: b, .. }) => *broken = b,
            (
                Self::FleetThread { thread, broken, .. },
                Self::FleetThread {
                    thread: t,
                    broken: b,
                    ..
                },
            ) => {
                *thread = t;
                *broken = b;
            }
            (Self::Server { broken, .. }, Self::Server { broken: b, .. }) => *broken = b,
            (Self::CloudRoom { broken }, Self::CloudRoom { broken: b }) => *broken = b,
            // One subject is always one check.
            _ => {}
        }
    }

    /// What its fix's tries make due next. `None`: the check has no fix.
    fn next(&self) -> Option<Next> {
        match self {
            Self::Loop { tries, .. } | Self::Tick { tries, .. } | Self::Server { tries, .. } => {
                Some(next(tries))
            }
            Self::FleetThread { tries, .. } => Some(next(tries)),
            Self::CloudRoom { .. } => None,
        }
    }

    /// Saves a try at `at`, its outcome not yet known.
    fn save_try(&mut self, at: Timestamp) {
        match self {
            Self::Loop { tries, .. } | Self::Tick { tries, .. } | Self::Server { tries, .. } => {
                save_try(tries, at)
            }
            Self::FleetThread { tries, .. } => save_try(tries, at),
            Self::CloudRoom { .. } => {}
        }
    }

    /// The fix for this incident's `attempt`. `None`: the check has no fix.
    fn fix(&self, incident: IncidentId, attempt: Try) -> Option<Fix> {
        match self {
            Self::Loop { subject, .. } => Some(Fix::ResumeLoop {
                incident,
                attempt,
                subject: subject.clone(),
            }),
            Self::Tick { .. } => Some(Fix::RestartTick { incident, attempt }),
            Self::FleetThread { spec, thread, .. } => Some(Fix::TakeOverFleetThread {
                incident,
                attempt,
                spec: *spec,
                thread: thread.clone(),
            }),
            Self::Server { .. } => Some(Fix::RestartServer { incident, attempt }),
            Self::CloudRoom { .. } => None,
        }
    }
}

/// What a fix's tries make due next.
enum Next {
    Try(Try),
    NeedsYou,
    /// A try is still running: its outcome isn't saved yet.
    Wait,
}

fn next<O>(tries: &Tries<O>) -> Next {
    match tries {
        Tries::Zero => Next::Try(Try::First),
        Tries::One(first) if first.outcome.is_some() => Next::Try(Try::Second),
        Tries::Two(first, second) if first.outcome.is_some() && second.outcome.is_some() => {
            Next::NeedsYou
        }
        Tries::One(_) | Tries::Two(..) => Next::Wait,
    }
}

fn save_try<O>(tries: &mut Tries<O>, at: Timestamp) {
    let new = SavedTry {
        at,
        outcome: None,
        comment: None,
    };
    *tries = match std::mem::replace(tries, Tries::Zero) {
        Tries::Zero => Tries::One(new),
        Tries::One(first) => Tries::Two(first, new),
        // Never: two tries make nothing more due.
        both @ Tries::Two(..) => both,
    };
}

/// A subject's observation in one result, as the two-tries rule reads it.
enum Observation {
    Healthy,
    /// Broken: the incident's fault, as this result shows it, with no tries.
    Broken(Fault),
    Unknown,
}

/// The subject and observation of `result`. `None` for an `unread` result,
/// which has no subject.
fn observation(result: &CheckResult) -> Option<(Subject<'_>, Observation)> {
    fn known<B>(observed: &Known<B>, fault: impl FnOnce(&B) -> Fault) -> Observation {
        match observed {
            Known::Healthy => Observation::Healthy,
            Known::Broken(broken) => Observation::Broken(fault(broken)),
        }
    }
    fn observed<B>(observed: &Observed<B>, fault: impl FnOnce(&B) -> Fault) -> Observation {
        match observed {
            Observed::Healthy => Observation::Healthy,
            Observed::Broken(broken) => Observation::Broken(fault(broken)),
            Observed::Unknown(_) => Observation::Unknown,
        }
    }
    Some(match result {
        CheckResult::Loop(LoopResult::Seen {
            subject,
            observed: o,
        }) => (
            Subject::Loop(&subject.id),
            observed(o, |broken| Fault::Loop {
                subject: subject.clone(),
                broken: *broken,
                tries: Tries::Zero,
            }),
        ),
        CheckResult::Tick { observed: o } => (
            Subject::Tick,
            known(o, |broken| Fault::Tick {
                broken: *broken,
                tries: Tries::Zero,
            }),
        ),
        CheckResult::FleetThread(FleetThreadResult::Seen {
            spec,
            thread,
            observed: o,
        }) => (
            Subject::FleetThread(*spec),
            observed(o, |broken| Fault::FleetThread {
                spec: *spec,
                thread: thread.clone(),
                broken: *broken,
                tries: Tries::Zero,
            }),
        ),
        CheckResult::Server { observed: o } => (
            Subject::Server,
            known(o, |broken| Fault::Server {
                broken: *broken,
                tries: Tries::Zero,
            }),
        ),
        CheckResult::CloudRoom { observed: o } => (
            Subject::CloudRoom,
            known(o, |broken| Fault::CloudRoom { broken: *broken }),
        ),
        CheckResult::Loop(LoopResult::Unread { .. })
        | CheckResult::FleetThread(FleetThreadResult::Unread { .. }) => return None,
    })
}

/// One pass of the two-tries rule over the open incidents.
struct Planner<'a> {
    now: Timestamp,
    next_incident: Number,
    incidents: Vec<Incident>,
    fixes: Vec<Fix>,
    needs_you: Vec<IncidentId>,
    new_op_id: &'a mut dyn FnMut() -> OpId,
}

impl Planner<'_> {
    /// The contract's steps 1 to 4 for one result.
    fn apply(&mut self, result: &CheckResult) {
        let Some((subject, observation)) = observation(result) else {
            // Unread: nothing changes.
            return;
        };
        let open = self
            .incidents
            .iter()
            .position(|i| i.fault.subject() == subject);
        match (open, observation) {
            (_, Observation::Unknown) | (None, Observation::Healthy) => {}
            (None, Observation::Broken(fault)) => self.open(fault),
            (Some(k), Observation::Broken(fault)) => {
                let incident = &mut self.incidents[k];
                incident.healthy_since = None;
                incident.fault.refresh(fault);
                self.advance(k);
            }
            (Some(k), Observation::Healthy) => match self.incidents[k].healthy_since {
                None => self.incidents[k].healthy_since = Some(self.now),
                Some(since) if self.now.0.saturating_sub(since.0) >= HEALTHY_FOR_MS => {
                    self.incidents.remove(k);
                }
                Some(_) => {}
            },
        }
    }

    /// Step 1: a new incident. Its fix's first try is due; a check with no
    /// fix has nothing due.
    fn open(&mut self, fault: Fault) {
        let id = IncidentId(self.next_incident);
        let Some(next_incident) = self.next_incident.checked_add(1) else {
            // No number is left for a new incident: none opens.
            return;
        };
        self.next_incident = next_incident;
        let has_fix = fault.next().is_some();
        self.incidents.push(Incident {
            id,
            fault,
            opened_at: self.now,
            healthy_since: None,
            needs_you: None,
        });
        if has_fix {
            self.advance(self.incidents.len() - 1);
        }
    }

    /// Step 2, for the open incident `k`, still broken: the next try, or
    /// its one "Needs you", or nothing.
    fn advance(&mut self, k: usize) {
        let incident = &mut self.incidents[k];
        match incident.fault.next() {
            Some(Next::Try(attempt)) => {
                incident.fault.save_try(self.now);
                self.fixes.extend(incident.fault.fix(incident.id, attempt));
            }
            // Both tries made, each with its outcome, or no fix at all.
            Some(Next::NeedsYou) | None if incident.needs_you.is_none() => {
                incident.needs_you = Some(NeedsYou {
                    at: self.now,
                    op_id: (self.new_op_id)(),
                    comment: None,
                });
                self.needs_you.push(incident.id);
            }
            // Its "Needs you" made, or a try still running: quiet.
            Some(Next::NeedsYou | Next::Wait) | None => {}
        }
    }

    /// Step 5: an incident whose subject is gone ends, when its check's
    /// list was read in full.
    fn end_gone(&mut self, results: &[CheckResult]) {
        let mut loops_read = true;
        let mut threads_read = true;
        let mut loops = BTreeSet::new();
        let mut specs = BTreeSet::new();
        for result in results {
            match result {
                CheckResult::Loop(LoopResult::Seen { subject, .. }) => {
                    loops.insert(&subject.id);
                }
                CheckResult::Loop(LoopResult::Unread { .. }) => loops_read = false,
                CheckResult::FleetThread(FleetThreadResult::Seen { spec, .. }) => {
                    specs.insert(*spec);
                }
                CheckResult::FleetThread(FleetThreadResult::Unread { .. }) => threads_read = false,
                CheckResult::Tick { .. }
                | CheckResult::Server { .. }
                | CheckResult::CloudRoom { .. } => {}
            }
        }
        self.incidents.retain(|incident| match &incident.fault {
            Fault::Loop { subject, .. } => !loops_read || loops.contains(&subject.id),
            Fault::FleetThread { spec, .. } => !threads_read || specs.contains(spec),
            Fault::Tick { .. } | Fault::Server { .. } | Fault::CloudRoom { .. } => true,
        });
    }
}
