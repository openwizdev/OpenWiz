//! The shell: screens, selection, the read lanes and the action seam. It does
//! no I/O itself: it asks for jobs ([`App::jobs`]), is told their results
//! ([`App::complete`]) and keys ([`App::key`]), and is drawn by
//! [`crate::render`]. Time comes in as [`Now`], so every rule is testable.

use std::cell::Cell;
use std::collections::{BTreeMap, VecDeque};

use crate::actions::{
    self, Action, ActionContext, ActionId, ActionInput, ActionRequest, ActionResult, ActionSeed,
    ActionView, Attempt, DecisionBinding, SnapshotData, Stage, TransportResult,
};
use crate::config::Settings;
use crate::http::{Failure, Reply, error_reason};
use crate::model::{self, Decisions, FleetDetail, Fleets, Inventory, SessionDetail};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Now {
    /// Monotonic milliseconds: every schedule and age of a local event.
    pub mono_ms: u64,
    /// Wall-clock Unix milliseconds: only for the age of server snapshots.
    pub wall_ms: i64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LaneKind {
    Decisions,
    Fleets,
    Inventory,
    SessionDetail,
    FleetDetail,
    CloudOptions,
    ActionPreview,
    OperationStatus,
}

/// A lane's timing: the existing clients' choices (terminal contract).
pub struct Timing {
    pub interval_ms: u64,
    pub backoff_ms: &'static [u64],
    pub stale_after_ms: u64,
}

pub const LATE_AFTER_MS: u64 = 45_000;
/// The client hold limit: a lane is never reused before its request ends,
/// and the transport's own deadline is this long.
pub const HOLD_MS: u64 = 70_000;
pub const MAX_READS_IN_FLIGHT: usize = 2;

impl LaneKind {
    pub fn timing(self) -> Timing {
        const QUICK: &[u64] = &[2_000, 4_000, 8_000, 16_000, 30_000];
        const SLOW: &[u64] = &[60_000, 120_000, 240_000, 300_000];
        match self {
            LaneKind::Inventory => Timing {
                interval_ms: 10_000,
                backoff_ms: QUICK,
                stale_after_ms: 30_000,
            },
            LaneKind::SessionDetail => Timing {
                interval_ms: 15_000,
                backoff_ms: QUICK,
                stale_after_ms: 30_000,
            },
            LaneKind::Decisions | LaneKind::Fleets | LaneKind::FleetDetail => Timing {
                interval_ms: 60_000,
                backoff_ms: SLOW,
                stale_after_ms: 70_000,
            },
            LaneKind::CloudOptions | LaneKind::ActionPreview | LaneKind::OperationStatus => {
                Timing {
                    interval_ms: u64::MAX,
                    backoff_ms: QUICK,
                    stale_after_ms: 30_000,
                }
            }
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            LaneKind::Decisions => "decisions",
            LaneKind::Fleets => "fleets",
            LaneKind::Inventory => "sessions",
            LaneKind::SessionDetail => "session",
            LaneKind::FleetDetail => "fleet",
            LaneKind::CloudOptions => "cloud options",
            LaneKind::ActionPreview => "preview",
            LaneKind::OperationStatus => "status",
        }
    }
}

/// One unit of work for the runtime.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Job {
    /// A read of an existing route.
    Read {
        id: u64,
        kind: LaneKind,
        target: String,
        path: String,
    },
    /// An action's request: a preview/status read, or one bound write.
    Action {
        id: u64,
        action: ActionId,
        request: ActionRequest,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Completion {
    Read {
        id: u64,
        result: Result<Reply, Failure>,
    },
    Action {
        id: u64,
        result: TransportResult,
    },
}

#[derive(Clone, Debug)]
struct InFlight {
    id: u64,
    target: String,
    started: u64,
}

#[derive(Clone, Debug, Default)]
struct Lane {
    in_flight: Option<InFlight>,
    next_due: u64,
    failures: u32,
    /// A manual refresh asked while a read was in flight.
    again: bool,
}

/// A good snapshot, kept until a newer good one replaces it.
#[derive(Clone, Debug)]
pub struct Good<T> {
    pub data: T,
    pub received_mono: u64,
    /// The wall-clock time of receipt, to measure the source's own age.
    pub received_wall: i64,
    pub generation: u64,
}

impl<T> Good<T> {
    /// The current age of a source-reported time `source_at`: its age at
    /// receipt by the wall clock (never negative), plus the monotonic time
    /// since. `None` when the source did not report one.
    pub fn age_of(&self, source_at: Option<i64>, now: Now) -> Option<u64> {
        let at_receipt = u64::try_from(self.received_wall.saturating_sub(source_at?)).unwrap_or(0);
        Some(at_receipt.saturating_add(now.mono_ms.saturating_sub(self.received_mono)))
    }
}

/// The last failure of a lane, shown beside its last good snapshot.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LaneError {
    pub reason: String,
    pub at_mono: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Nav {
    Home,
    Sessions,
    Fleets,
}

/// The identity of one Needs you item, as displayed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NeedKey {
    Decision {
        repository: String,
        comment_id: u64,
        fingerprint: String,
        /// The grill question this item is, or `None` for a whole record.
        question: Option<String>,
    },
    Fleet {
        kind: String,
        spec: u64,
        ticket: u64,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Detail {
    Session(String),
    Fleet(u64),
    Need(NeedKey),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Key {
    Char(char),
    Ctrl(char),
    Up,
    Down,
    Enter,
    Esc,
    Tab,
    BackTab,
    Backspace,
    PageUp,
    PageDown,
}

/// One key event. `repeat` is an auto-repeat (or an unknown kind that may
/// be one); it can move a cursor but never confirms.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct KeyPress {
    pub key: Key,
    pub repeat: bool,
    /// A reported key release (only with release reporting).
    pub release: bool,
}

impl KeyPress {
    pub fn press(key: Key) -> Self {
        Self {
            key,
            repeat: false,
            release: false,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Flow {
    Continue,
    Quit,
}

struct OpenAction {
    id: ActionId,
    focus: usize,
    /// The displayed seed, retained independently of later reads/reordering.
    decision: Option<DecisionBinding>,
}

pub struct App {
    pub settings: Settings,
    pub nav: Nav,
    pub detail: Option<Detail>,
    pub selected_session: Option<String>,
    pub selected_fleet: Option<u64>,
    pub scroll: usize,
    pub decisions: Option<Good<Decisions>>,
    pub fleets: Option<Good<Fleets>>,
    pub inventory: Option<Good<Inventory>>,
    pub sessions: BTreeMap<String, Good<SessionDetail>>,
    pub fleet_details: BTreeMap<u64, Good<FleetDetail>>,
    pub errors: BTreeMap<LaneKind, LaneError>,
    /// One line about the last thing the shell refused or explained.
    pub notice: Option<String>,
    pub attempts: Vec<Attempt>,
    pub action_views: BTreeMap<ActionId, ActionView>,
    lanes: BTreeMap<LaneKind, Lane>,
    actions: Vec<(ActionId, Option<Box<dyn Action>>)>,
    open: Option<OpenAction>,
    /// Action read requests waiting for their lane: latest only per lane.
    action_pending: BTreeMap<LaneKind, (ActionId, ActionRequest, Option<String>)>,
    action_jobs: BTreeMap<u64, (ActionId, Option<LaneKind>, Option<String>)>,
    queued: VecDeque<Job>,
    generation: u64,
    next_id: u64,
    press: u64,
    /// A confirmation may be issued: set when an action opens, spent by
    /// each confirmation, and set again only by a reported release of the
    /// confirm key or, without release reporting, by a different key.
    confirm_armed: bool,
    /// Without release reporting, confirmations alternate Ctrl-S, Ctrl-Y,
    /// Ctrl-S…: one held key repeats only itself, so it can never make two.
    next_confirm_y: bool,
    pub key_release_reported: bool,
    /// Home's selected Needs you item, by identity.
    pub selected_need: Option<NeedKey>,
    /// Keep the selected row in view (after a move), rather than the
    /// owner's own scroll position (after a page key).
    pub follow: bool,
    /// What the last draw showed: the first visual row, the largest
    /// possible first row and the height. Page keys move from these.
    pub view_offset: Cell<usize>,
    pub view_max: Cell<usize>,
    pub view_height: Cell<u16>,
    /// The action pane's own scroll, the same way.
    pub action_scroll: usize,
    pub action_follow: bool,
    pub action_offset: Cell<usize>,
    pub action_max: Cell<usize>,
    pub action_height: Cell<u16>,
    /// The last draw showed the open action's exact target on one line.
    /// Until a draw says so, nothing can be confirmed.
    pub target_shown: Cell<bool>,
}

impl App {
    pub fn new(settings: Settings) -> Self {
        Self::with_actions(settings, actions::registry())
    }

    /// The shell with a given registration (tests register fixture actions).
    pub fn with_actions(
        settings: Settings,
        actions: Vec<(ActionId, Option<Box<dyn Action>>)>,
    ) -> Self {
        let mut lanes = BTreeMap::new();
        for kind in [
            LaneKind::Decisions,
            LaneKind::Fleets,
            LaneKind::Inventory,
            LaneKind::SessionDetail,
            LaneKind::FleetDetail,
            LaneKind::CloudOptions,
            LaneKind::ActionPreview,
            LaneKind::OperationStatus,
        ] {
            lanes.insert(kind, Lane::default());
        }
        Self {
            settings,
            nav: Nav::Home,
            detail: None,
            selected_session: None,
            selected_fleet: None,
            scroll: 0,
            decisions: None,
            fleets: None,
            inventory: None,
            sessions: BTreeMap::new(),
            fleet_details: BTreeMap::new(),
            errors: BTreeMap::new(),
            notice: None,
            attempts: Vec::new(),
            action_views: BTreeMap::new(),
            lanes,
            actions,
            open: None,
            action_pending: BTreeMap::new(),
            action_jobs: BTreeMap::new(),
            queued: VecDeque::new(),
            generation: 0,
            next_id: 0,
            press: 0,
            confirm_armed: false,
            next_confirm_y: false,
            key_release_reported: false,
            selected_need: None,
            follow: true,
            view_offset: Cell::new(0),
            view_max: Cell::new(0),
            view_height: Cell::new(1),
            action_scroll: 0,
            action_follow: true,
            action_offset: Cell::new(0),
            action_max: Cell::new(0),
            action_height: Cell::new(1),
            target_shown: Cell::new(false),
        }
    }

    /// The capability ids of the registered actions.
    pub fn available_actions(&self) -> Vec<ActionId> {
        self.actions
            .iter()
            .filter(|(_, a)| a.is_some())
            .map(|(id, _)| *id)
            .collect()
    }

    pub fn action_available(&self, id: ActionId) -> bool {
        self.actions.iter().any(|(i, a)| *i == id && a.is_some())
    }

    pub fn open_action(&self) -> Option<ActionId> {
        self.open.as_ref().map(|o| o.id)
    }

    pub fn action_focus(&self) -> usize {
        self.open.as_ref().map_or(0, |o| o.focus)
    }

    pub fn in_flight(&self, kind: LaneKind) -> Option<(String, u64)> {
        self.lanes[&kind]
            .in_flight
            .as_ref()
            .map(|f| (f.target.clone(), f.started))
    }

    pub fn reads_in_flight(&self) -> usize {
        self.lanes
            .values()
            .filter(|l| l.in_flight.is_some())
            .count()
    }

    pub fn failures(&self, kind: LaneKind) -> u32 {
        self.lanes[&kind].failures
    }

    pub fn next_due(&self, kind: LaneKind) -> u64 {
        self.lanes[&kind].next_due
    }

    /// The Needs you items, in display order: the decision records first
    /// (a grill round as one item per unanswered question, in order), then
    /// the fleet-only held/needs-info facts. Numbers are 1-based positions in
    /// this list.
    pub fn needs(&self) -> Vec<NeedKey> {
        let mut keys = Vec::new();
        if let Some(d) = &self.decisions {
            for item in &d.data.items {
                let key = |question: Option<String>| NeedKey::Decision {
                    repository: item.repository.clone(),
                    comment_id: item.comment_id,
                    fingerprint: item.fingerprint.clone(),
                    question,
                };
                if item.kind == "grill_round" {
                    keys.extend(item.questions.iter().map(|q| key(Some(q.id.clone()))));
                } else {
                    keys.push(key(None));
                }
            }
        }
        if let Some(f) = &self.fleets
            && let model::Fact::Known(needs) = &f.data.needs_you
        {
            for n in needs {
                keys.push(NeedKey::Fleet {
                    kind: n.kind.clone(),
                    spec: n.spec,
                    ticket: n.ticket,
                });
            }
        }
        keys
    }

    /// Sessions shown in lists: every session the inventory returned, in its
    /// order (most recently updated first).
    pub fn session_ids(&self) -> Vec<String> {
        self.inventory
            .as_ref()
            .map(|i| i.data.sessions.iter().map(|s| s.id.clone()).collect())
            .unwrap_or_default()
    }

    pub fn fleet_specs(&self) -> Vec<u64> {
        self.fleets
            .as_ref()
            .map(|f| f.data.fleets.iter().map(|f| f.spec).collect())
            .unwrap_or_default()
    }

    fn lane_target(&self, kind: LaneKind) -> Option<(String, String)> {
        match kind {
            LaneKind::Decisions => Some((String::new(), "/api/v1/decisions".into())),
            LaneKind::Fleets => Some((String::new(), "/api/v1/fleets".into())),
            LaneKind::Inventory => Some((String::new(), "/api/v1/inventory".into())),
            LaneKind::SessionDetail => match &self.detail {
                Some(Detail::Session(id)) => Some((id.clone(), format!("/api/v1/sessions/{id}"))),
                _ => None,
            },
            LaneKind::FleetDetail => match &self.detail {
                Some(Detail::Fleet(spec)) => {
                    Some((spec.to_string(), format!("/api/v1/fleets/{spec}")))
                }
                _ => None,
            },
            _ => None,
        }
    }

    /// The reads and action requests due now. Never more than one read per
    /// lane kind, nor more than two reads in all.
    pub fn jobs(&mut self, now: Now) -> Vec<Job> {
        let mut jobs: Vec<Job> = self.queued.drain(..).collect();
        let mut order = vec![
            LaneKind::ActionPreview,
            LaneKind::OperationStatus,
            LaneKind::CloudOptions,
        ];
        match self.detail {
            Some(Detail::Session(_)) => order.push(LaneKind::SessionDetail),
            Some(Detail::Fleet(_)) => order.push(LaneKind::FleetDetail),
            _ => {}
        }
        order.extend([LaneKind::Decisions, LaneKind::Inventory, LaneKind::Fleets]);
        for kind in order {
            if self.reads_in_flight() >= MAX_READS_IN_FLIGHT {
                break;
            }
            if self.lanes[&kind].in_flight.is_some() {
                continue;
            }
            if let Some((action, request, op_id)) = self.action_pending.remove(&kind) {
                let id = self.id();
                self.lanes.get_mut(&kind).unwrap().in_flight = Some(InFlight {
                    id,
                    target: String::new(),
                    started: now.mono_ms,
                });
                self.action_jobs.insert(id, (action, Some(kind), op_id));
                jobs.push(Job::Action {
                    id,
                    action,
                    request,
                });
                continue;
            }
            let Some((target, path)) = self.lane_target(kind) else {
                continue;
            };
            if now.mono_ms < self.lanes[&kind].next_due {
                continue;
            }
            let id = self.id();
            self.lanes.get_mut(&kind).unwrap().in_flight = Some(InFlight {
                id,
                target: target.clone(),
                started: now.mono_ms,
            });
            jobs.push(Job::Read {
                id,
                kind,
                target,
                path,
            });
        }
        jobs
    }

    fn id(&mut self) -> u64 {
        self.next_id += 1;
        self.next_id
    }

    /// A finished job. A read that ended after its selection changed is kept
    /// under its own target and never shown as another's.
    pub fn complete(&mut self, completion: Completion, now: Now) {
        match completion {
            Completion::Read { id, result } => self.complete_read(id, result, now),
            Completion::Action { id, result } => self.complete_action(id, result, now),
        }
    }

    fn complete_read(&mut self, id: u64, result: Result<Reply, Failure>, now: Now) {
        let Some((kind, target)) = self.lanes.iter().find_map(|(k, l)| {
            l.in_flight
                .as_ref()
                .filter(|f| f.id == id)
                .map(|f| (*k, f.target.clone()))
        }) else {
            return;
        };
        let lane = self.lanes.get_mut(&kind).unwrap();
        lane.in_flight = None;
        let parsed = result
            .map_err(|f| (f.reason, None))
            .and_then(|reply| {
                if reply.status != 200 {
                    return Err((error_reason(&reply), reply.retry_after));
                }
                crate::json::parse(&reply.body).map_err(|e| (e, None))
            })
            .and_then(|value| {
                self.store(kind, &target, &value, now)
                    .map_err(|e| (e, None))
            });
        let timing = kind.timing();
        let lane = self.lanes.get_mut(&kind).unwrap();
        match parsed {
            Ok(()) => {
                lane.failures = 0;
                lane.next_due = now.mono_ms + timing.interval_ms;
                self.errors.remove(&kind);
            }
            Err((reason, retry_after)) => {
                lane.failures += 1;
                let step = (lane.failures as usize - 1).min(timing.backoff_ms.len() - 1);
                let cap = *timing.backoff_ms.last().unwrap();
                let wait = timing.backoff_ms[step]
                    .max(retry_after.map_or(0, |s| s.saturating_mul(1000)).min(cap));
                lane.next_due = now.mono_ms + wait;
                self.errors.insert(
                    kind,
                    LaneError {
                        reason,
                        at_mono: now.mono_ms,
                    },
                );
            }
        }
        let current = self.lane_target_key(kind);
        let lane = self.lanes.get_mut(&kind).unwrap();
        if lane.again || current.is_some_and(|c| c != target) {
            lane.again = false;
            lane.next_due = now.mono_ms;
        }
    }

    fn lane_target_key(&self, kind: LaneKind) -> Option<String> {
        self.lane_target(kind).map(|(t, _)| t)
    }

    fn store(
        &mut self,
        kind: LaneKind,
        target: &str,
        value: &serde_json::Value,
        now: Now,
    ) -> Result<(), String> {
        self.generation += 1;
        let generation = self.generation;
        fn good<T>(data: T, now: Now, generation: u64) -> Good<T> {
            Good {
                data,
                received_mono: now.mono_ms,
                received_wall: now.wall_ms,
                generation,
            }
        }
        let snapshot = match kind {
            LaneKind::Decisions => {
                // The whole response against its contract first: its records
                // bind answers, so a malformed one is never shown as data.
                crate::schema::validate_report("openwiz.decisions.v1", value)?;
                let data = model::decisions(value)?;
                self.decisions = Some(good(data.clone(), now, generation));
                SnapshotData::Decisions(data)
            }
            LaneKind::Fleets => {
                let data = model::fleets(value)?;
                self.fleets = Some(good(data.clone(), now, generation));
                SnapshotData::Fleets(data)
            }
            LaneKind::Inventory => {
                let data = model::inventory(value)?;
                self.inventory = Some(good(data.clone(), now, generation));
                SnapshotData::Inventory(data)
            }
            LaneKind::SessionDetail => {
                let data = model::session_detail(value)?;
                if data.session.id != target {
                    return Err("the session detail is for another session".into());
                }
                self.sessions
                    .insert(target.to_owned(), good(data.clone(), now, generation));
                SnapshotData::Session(data)
            }
            LaneKind::FleetDetail => {
                let data = model::fleet_detail(value)?;
                if data.fleet.spec.to_string() != target {
                    return Err("the fleet detail is for another fleet".into());
                }
                self.fleet_details
                    .insert(data.fleet.spec, good(data.clone(), now, generation));
                SnapshotData::Fleet(data)
            }
            _ => return Ok(()),
        };
        // Tell every open action about the new snapshot. A snapshot can never
        // produce a dispatch: the shell refuses one below.
        if let Some(open) = self.open.as_ref().map(|o| o.id) {
            self.deliver(
                open,
                ActionInput::Snapshot {
                    generation,
                    data: snapshot,
                },
                now,
            );
        }
        Ok(())
    }

    fn complete_action(&mut self, id: u64, result: TransportResult, now: Now) {
        let Some((action, lane, op_id)) = self.action_jobs.remove(&id) else {
            return;
        };
        if let Some(kind) = lane
            && let Some(l) = self.lanes.get_mut(&kind)
            && l.in_flight.as_ref().is_some_and(|f| f.id == id)
        {
            l.in_flight = None;
        }
        if let Some(attempt) = self.attempts.iter_mut().find(|a| {
            a.action == action
                && Some(&a.op_id) == op_id.as_ref()
                && a.stage == Stage::Dispatching
                && lane.is_none()
        }) {
            attempt.outcome = Some(result.clone());
            attempt.stage = Stage::Settled;
            attempt.retain_settlement();
        } else if lane == Some(LaneKind::OperationStatus)
            && let Some(attempt) = self
                .attempts
                .iter_mut()
                .find(|a| a.action == action && Some(&a.op_id) == op_id.as_ref())
        {
            attempt.last_status = Some(result.clone());
            attempt.retain_settlement();
        }
        // The job id identifies the request kind and the draft/operation
        // captured when it was queued. A preview has no wire operation id,
        // but still belongs only to that draft, never an attempt's outcome.
        if !self.action_response_is_current(action, lane, op_id.as_deref()) {
            return;
        }
        self.deliver(
            action,
            ActionInput::Response {
                request_id: id,
                result,
            },
            now,
        );
    }

    fn action_response_is_current(
        &self,
        action: ActionId,
        lane: Option<LaneKind>,
        op_id: Option<&str>,
    ) -> bool {
        if action != ActionId::Answer {
            return true;
        }
        let Some(op_id) = op_id else {
            return false;
        };
        self.action_views
            .get(&action)
            .and_then(|v| v.op_id.as_deref())
            == Some(op_id)
            && (lane != Some(LaneKind::ActionPreview)
                || !self
                    .attempts
                    .iter()
                    .any(|a| a.action == action && a.op_id == op_id))
    }

    /// The decision binding of a displayed Needs you record, from the same
    /// response that displayed it.
    pub fn binding(&self, key: &NeedKey) -> Option<DecisionBinding> {
        let NeedKey::Decision {
            repository,
            comment_id,
            fingerprint,
            question,
        } = key
        else {
            return None;
        };
        let good = self.decisions.as_ref()?;
        let d = &good.data;
        let item = d.items.iter().find(|i| {
            &i.repository == repository
                && i.comment_id == *comment_id
                && &i.fingerprint == fingerprint
        })?;
        // A grill question binds only while it is listed and unanswered; a
        // whole record binds only when it is not a grill round.
        let (proposal, recommendation, context) = match question {
            Some(id) => {
                let q = item.questions.iter().find(|q| &q.id == id)?;
                (
                    vec![q.decides.clone()],
                    vec![q.recommendation.clone()],
                    vec![q.context.clone()],
                )
            }
            None if item.kind == "grill_round" => return None,
            None => (item.wording.clone(), Vec::new(), Vec::new()),
        };
        Some(DecisionBinding {
            repository: item.repository.clone(),
            subject_kind: item.subject_kind.clone(),
            subject_number: item.subject_number,
            comment_id: item.comment_id,
            request_id: item.id.clone(),
            fingerprint: item.fingerprint.clone(),
            question_id: question.clone(),
            proposal,
            recommendation,
            context,
            record: item.record.clone(),
            risk: item.risk.clone(),
            current: item.current.clone(),
            source_freshness: d.freshness,
            source_snapshot_at: d.source_snapshot_at.clone(),
            generation: good.generation,
            target: d.target.clone(),
            target_freshness: d.target_freshness,
            target_snapshot_at: d.target_snapshot_at.clone(),
        })
    }

    /// Hands one input to an action and applies the shell's rules to what it
    /// returns: only a distinct confirmation may yield a write, at most one
    /// unresolved write per action, recorded and marked dispatched first.
    fn deliver(&mut self, id: ActionId, input: ActionInput, now: Now) {
        let confirm = matches!(input, ActionInput::Confirm { .. });
        let decisions = self.decisions.as_ref().map(|g| g.data.clone());
        let inventory = self.inventory.as_ref().map(|g| g.data.clone());
        let fleets = self.fleets.as_ref().map(|g| g.data.clone());
        let decision_ages = self.decisions.as_ref().map(|g| actions::DecisionAges {
            sources_age_ms: g.age_of(g.data.source_snapshot_at.known().copied(), now),
            target_age_ms: g.age_of(g.data.target_snapshot_at.known().copied(), now),
        });
        let decision = match &input {
            ActionInput::Open(ActionSeed::Answer(binding)) => Some(binding.clone()),
            _ => self
                .open
                .as_ref()
                .filter(|o| o.id == id)
                .and_then(|o| o.decision.clone()),
        };
        let context_attempt = if id == ActionId::Answer {
            // Updates/status belong to the operation actually displayed,
            // including an earlier attempt shown while another item is
            // blocked. Explicit Open instead selects that item's history.
            let displayed = if matches!(&input, ActionInput::Open(_)) {
                None
            } else {
                self.action_views
                    .get(&id)
                    .and_then(|view| view.op_id.as_ref())
                    .and_then(|op| {
                        self.attempts
                            .iter()
                            .find(|a| a.action == id && &a.op_id == op)
                    })
            };
            displayed
                .or_else(|| {
                    self.attempts.iter().rev().find(|a| {
                        a.action == id && a.blocks_answer(decisions.as_ref(), decision_ages)
                    })
                })
                .or_else(|| {
                    self.attempts.iter().rev().find(|a| {
                        a.action == id
                            && decision.as_ref().is_some_and(|b| {
                                a.decision.as_ref().is_some_and(|old| old.same_item(b))
                            })
                    })
                })
        } else {
            self.attempts.iter().rev().find(|a| a.action == id)
        }
        .cloned();
        let context = ActionContext {
            generation: self.generation,
            decision_ages,
            decisions: decisions.as_ref(),
            inventory: inventory.as_ref(),
            fleets: fleets.as_ref(),
            guarded_available: self.settings.allowed_host.is_some(),
            attempt: context_attempt.as_ref(),
        };
        let Some(action) = self
            .actions
            .iter_mut()
            .find(|(i, _)| *i == id)
            .and_then(|(_, a)| a.as_mut())
        else {
            return;
        };
        let ActionResult { view, request } = action.update(input, &context);
        self.action_views.insert(id, view);
        let Some(request) = request else {
            return;
        };
        if request.is_dispatch() {
            if !confirm {
                self.notice = Some(format!(
                    "{}: refused a write that did not come from a confirmation; nothing was sent",
                    id.label()
                ));
                return;
            }
            let blocked = self.attempts.iter().any(|a| {
                a.action == id
                    && if id == ActionId::Answer {
                        a.blocks_answer(decisions.as_ref(), decision_ages)
                            || decision.as_ref().is_some_and(|b| {
                                a.decision.as_ref().is_some_and(|old| old.same_item(b))
                                    && !a.safe_to_reopen()
                            })
                    } else {
                        a.locked()
                    }
            });
            if blocked || (id == ActionId::Answer && decision.is_none()) {
                self.notice = Some(format!(
                    "{}: an earlier attempt may have been sent; check its status instead. Nothing was sent",
                    id.label()
                ));
                return;
            }
            if self.settings.allowed_host.is_none() {
                self.notice = Some(format!(
                    "{}: no allowed host is configured, so nothing can be sent",
                    id.label()
                ));
                return;
            }
            let job = self.id();
            self.attempts.push(Attempt {
                action: id,
                op_id: request.op_id().unwrap_or_default().to_owned(),
                request: request.clone(),
                decision,
                preview_generation: self.generation,
                stage: Stage::Dispatching,
                dispatched: true,
                outcome: None,
                last_status: None,
                confirmed_outcome: None,
            });
            self.action_jobs
                .insert(job, (id, None, request.op_id().map(str::to_owned)));
            self.queued.push_back(Job::Action {
                id: job,
                action: id,
                request,
            });
            return;
        }
        let kind = match request {
            ActionRequest::Options => LaneKind::CloudOptions,
            ActionRequest::Lookup { .. } | ActionRequest::Status { .. } => {
                LaneKind::OperationStatus
            }
            _ => LaneKind::ActionPreview,
        };
        let op_id = if id == ActionId::Answer && kind == LaneKind::ActionPreview {
            // Capture ownership now, even when another preview keeps this
            // read queued until after the owner has opened another item.
            self.action_views.get(&id).and_then(|v| v.op_id.clone())
        } else {
            request.op_id().map(str::to_owned)
        };
        if let Some((displaced, _, displaced_op)) =
            self.action_pending.insert(kind, (id, request, op_id))
            && displaced != id
            && self.action_response_is_current(displaced, Some(kind), displaced_op.as_deref())
        {
            // This queued read never got a transport job. Complete its
            // displaced owner so a later explicit status check can run.
            // Keep the latest queued read and every write/attempt guard.
            let request_id = self.id();
            self.deliver(
                displaced,
                ActionInput::Response {
                    request_id,
                    result: TransportResult::FailedBeforeDispatch {
                        reason: "read superseded by another action; it was not dispatched".into(),
                    },
                },
                now,
            );
        }
    }

    /// Asks every active lane for an earlier read, through the same lanes.
    pub fn refresh(&mut self, now: Now) {
        for kind in [
            LaneKind::Decisions,
            LaneKind::Fleets,
            LaneKind::Inventory,
            LaneKind::SessionDetail,
            LaneKind::FleetDetail,
        ] {
            let lane = self.lanes.get_mut(&kind).unwrap();
            if lane.in_flight.is_some() {
                lane.again = true;
            } else {
                lane.next_due = now.mono_ms;
            }
        }
    }

    fn go(&mut self, nav: Nav, now: Now) {
        self.nav = nav;
        self.detail = None;
        self.reset_view();
        let _ = now;
    }

    fn open_detail(&mut self, detail: Detail, now: Now) {
        let kind = match &detail {
            Detail::Session(_) => Some(LaneKind::SessionDetail),
            Detail::Fleet(_) => Some(LaneKind::FleetDetail),
            Detail::Need(_) => None,
        };
        self.detail = Some(detail);
        self.reset_view();
        if let Some(kind) = kind {
            let lane = self.lanes.get_mut(&kind).unwrap();
            if lane.in_flight.is_none() {
                lane.next_due = now.mono_ms;
            }
        }
    }

    fn reset_view(&mut self) {
        self.scroll = 0;
        self.follow = true;
        self.view_offset.set(0);
    }

    /// Scrolls by `delta` visual rows from what the last draw showed,
    /// within what it could show.
    fn scroll_by(&mut self, delta: i64) {
        // While the owner scrolls, keys pressed between draws add up.
        let shown = if self.follow {
            self.view_offset.get()
        } else {
            self.scroll.min(self.view_max.get())
        };
        let from = shown as i64;
        let to = (from + delta).clamp(0, self.view_max.get() as i64);
        self.scroll = to as usize;
        self.follow = false;
    }

    fn page(&mut self, down: bool) {
        let page = i64::from(self.view_height.get().saturating_sub(1).max(1));
        self.scroll_by(if down { page } else { -page });
    }

    /// Up and down: the selection in a list (kept in view), or one row of a
    /// detail.
    fn move_cursor(&mut self, delta: i64) {
        if self.detail.is_some() {
            self.scroll_by(delta);
            return;
        }
        self.follow = true;
        match self.nav {
            Nav::Sessions => {
                let ids = self.session_ids();
                self.selected_session = step(&ids, self.selected_session.as_ref(), delta);
            }
            Nav::Fleets => {
                let specs = self.fleet_specs();
                self.selected_fleet = step(&specs, self.selected_fleet.as_ref(), delta);
            }
            Nav::Home => {
                let needs = self.needs();
                self.selected_need = step(&needs, self.selected_need.as_ref(), delta);
            }
        }
    }

    /// The seed for an action from what is selected, if it is ready.
    fn seed(&self, id: ActionId) -> Result<ActionSeed, &'static str> {
        match (id, &self.detail) {
            (ActionId::Answer, Some(Detail::Need(key))) => self
                .binding(key)
                .map(ActionSeed::Answer)
                .ok_or("this item carries no answerable proposal"),
            (ActionId::Send, Some(Detail::Session(id))) => Ok(ActionSeed::Send {
                session_id: id.clone(),
            }),
            (ActionId::NewThread, _) => {
                let id = match &self.detail {
                    Some(Detail::Session(id)) => Some(id.clone()),
                    None if self.nav == Nav::Sessions => self.selected_session.clone(),
                    _ => None,
                };
                let project = id.and_then(|id| {
                    self.inventory.as_ref().and_then(|i| {
                        i.data
                            .sessions
                            .iter()
                            .find(|s| s.id == id)
                            .and_then(|s| s.project.as_ref().map(|p| p.0.clone()))
                    })
                });
                project
                    .map(|project_id| ActionSeed::NewThread { project_id })
                    .ok_or("select a session in a known project first")
            }
            _ => Err("open the item this action is for first"),
        }
    }

    fn start_action(&mut self, id: ActionId, now: Now) {
        if !self.action_available(id) {
            self.notice = Some(format!(
                "{} is not available in this build; nothing was sent",
                id.label()
            ));
            return;
        }
        match self.seed(id) {
            Ok(seed) => {
                self.open = Some(OpenAction {
                    id,
                    focus: 0,
                    decision: match &seed {
                        ActionSeed::Answer(binding) => Some(binding.clone()),
                        _ => None,
                    },
                });
                self.confirm_armed = true;
                self.next_confirm_y = false;
                self.action_scroll = 0;
                self.action_follow = true;
                self.action_offset.set(0);
                self.target_shown.set(false);
                self.deliver(id, ActionInput::Open(seed), now);
            }
            Err(why) => self.notice = Some(format!("{}: {why}", id.label())),
        }
    }

    fn action_key(&mut self, press: KeyPress, now: Now) -> Flow {
        if press.release {
            if press.key == Key::Ctrl('s') {
                self.confirm_armed = true;
            }
            return Flow::Continue;
        }
        let open = self.open.as_ref().map(|o| (o.id, o.focus)).unwrap();
        let (id, focus) = open;
        let fields = self
            .action_views
            .get(&id)
            .map(|v| v.fields.clone())
            .unwrap_or_default();
        let editable: Vec<_> = fields.iter().filter(|f| f.3).collect();
        match press.key {
            Key::Ctrl('c') => return Flow::Quit,
            Key::Esc => {
                self.deliver(id, ActionInput::Cancel, now);
                self.open = None;
            }
            Key::Tab | Key::BackTab if !editable.is_empty() => {
                let n = editable.len();
                let next = if press.key == Key::Tab {
                    (focus + 1) % n
                } else {
                    (focus + n - 1) % n
                };
                self.open.as_mut().unwrap().focus = next;
                self.action_follow = true;
            }
            Key::Ctrl('p') => self.deliver(id, ActionInput::Preview, now),
            Key::Ctrl('r') => self.deliver(id, ActionInput::RefreshStatus, now),
            Key::Ctrl(c @ ('s' | 'y')) => {
                let expected = self.confirm_key();
                if press.repeat {
                    self.notice = Some("A held key never confirms. Nothing was sent.".into());
                } else if c != expected {
                    self.notice = Some(format!(
                        "Press Ctrl-{} to confirm. Nothing was sent.",
                        expected.to_ascii_uppercase()
                    ));
                } else if !self.target_shown.get() {
                    self.notice = Some(
                        "The window is too small to show the exact target; enlarge it to confirm. Nothing was sent."
                            .into(),
                    );
                } else if self.key_release_reported && !self.confirm_armed {
                    self.notice = Some(
                        "Release the key and press it again to confirm once more. Nothing was sent."
                            .into(),
                    );
                } else {
                    // Spent: a release (where reported) re-arms Ctrl-S;
                    // otherwise the next confirmation is the other key.
                    self.confirm_armed = false;
                    self.next_confirm_y = !self.key_release_reported && !self.next_confirm_y;
                    self.press += 1;
                    let press_id = self.press;
                    self.deliver(id, ActionInput::Confirm { press_id }, now);
                }
            }
            Key::PageDown | Key::PageUp => {
                let page = self.action_height.get().saturating_sub(1).max(1);
                let page = usize::from(page);
                let from = if self.action_follow {
                    self.action_offset.get()
                } else {
                    self.action_scroll.min(self.action_max.get())
                };
                let to = if press.key == Key::PageDown {
                    from.saturating_add(page).min(self.action_max.get())
                } else {
                    from.saturating_sub(page)
                };
                self.action_scroll = to;
                self.action_follow = false;
            }
            Key::Char(c) | Key::Ctrl(c @ 'j') if !editable.is_empty() => {
                let c = if press.key == Key::Ctrl('j') { '\n' } else { c };
                let (field, _, value, _) = editable[focus.min(editable.len() - 1)].clone();
                let mut value = value;
                value.push(c);
                self.deliver(id, ActionInput::Edit { field, value }, now);
            }
            Key::Backspace if !editable.is_empty() => {
                let (field, _, value, _) = editable[focus.min(editable.len() - 1)].clone();
                let mut value = value;
                value.pop();
                self.deliver(id, ActionInput::Edit { field, value }, now);
            }
            _ => {}
        }
        Flow::Continue
    }

    /// The key the next confirmation needs: Ctrl-S, or, without release
    /// reporting after a confirmation, Ctrl-Y (then Ctrl-S again).
    pub fn confirm_key(&self) -> char {
        if self.next_confirm_y { 'y' } else { 's' }
    }

    /// Pasted text (bracketed paste): typed into the open action's focused
    /// field as it is, and nothing else. A paste never confirms and never
    /// re-arms confirmation, whatever it contains.
    pub fn paste(&mut self, text: &str, now: Now) {
        let Some((id, focus)) = self.open.as_ref().map(|o| (o.id, o.focus)) else {
            return;
        };
        let editable: Vec<_> = self
            .action_views
            .get(&id)
            .map(|v| v.fields.iter().filter(|f| f.3).cloned().collect())
            .unwrap_or_default();
        if let Some((field, _, value, _)) =
            editable.get(focus.min(editable.len().saturating_sub(1)))
        {
            let value = format!("{value}{text}");
            self.deliver(
                id,
                ActionInput::Edit {
                    field: field.clone(),
                    value,
                },
                now,
            );
        }
    }

    /// One key. Navigation and refresh only read; no key but an action's
    /// distinct confirmation can lead to a write.
    pub fn key(&mut self, press: KeyPress, now: Now) -> Flow {
        if press.release && self.open.is_none() {
            return Flow::Continue;
        }
        if self.open.is_some() {
            return self.action_key(press, now);
        }
        self.notice = None;
        match press.key {
            Key::Ctrl('c') | Key::Char('q') => return Flow::Quit,
            Key::Char('h') => self.go(Nav::Home, now),
            Key::Char('s') => self.go(Nav::Sessions, now),
            Key::Char('f') => self.go(Nav::Fleets, now),
            Key::Tab => {
                let next = match self.nav {
                    Nav::Home => Nav::Sessions,
                    Nav::Sessions => Nav::Fleets,
                    Nav::Fleets => Nav::Home,
                };
                self.go(next, now);
            }
            Key::BackTab => {
                let next = match self.nav {
                    Nav::Home => Nav::Fleets,
                    Nav::Sessions => Nav::Home,
                    Nav::Fleets => Nav::Sessions,
                };
                self.go(next, now);
            }
            Key::Char('r') => {
                self.refresh(now);
                self.notice = Some("refresh requested".into());
            }
            Key::Char(c @ '1'..='9') if self.nav == Nav::Home && self.detail.is_none() => {
                let n = c as usize - '0' as usize;
                match self.needs().get(n - 1) {
                    Some(key) => self.open_detail(Detail::Need(key.clone()), now),
                    None => self.notice = Some(format!("there is no item {n}")),
                }
            }
            Key::Up | Key::Char('k') => self.move_cursor(-1),
            Key::Down | Key::Char('j') => self.move_cursor(1),
            Key::PageUp => self.page(false),
            Key::PageDown => self.page(true),
            Key::Enter if self.detail.is_none() => match self.nav {
                Nav::Sessions => {
                    if let Some(id) = self
                        .selected_session
                        .clone()
                        .or_else(|| self.session_ids().first().cloned())
                    {
                        self.selected_session = Some(id.clone());
                        self.open_detail(Detail::Session(id), now);
                    }
                }
                Nav::Fleets => {
                    if let Some(spec) = self
                        .selected_fleet
                        .or_else(|| self.fleet_specs().first().copied())
                    {
                        self.selected_fleet = Some(spec);
                        self.open_detail(Detail::Fleet(spec), now);
                    }
                }
                Nav::Home => {
                    // Only an item still listed opens; never a neighbour.
                    if let Some(key) = self.selected_need.clone()
                        && self.needs().contains(&key)
                    {
                        self.open_detail(Detail::Need(key), now);
                    }
                }
            },
            Key::Esc | Key::Backspace => {
                self.detail = None;
                self.scroll = 0;
            }
            Key::Char('a') => self.start_action(ActionId::Answer, now),
            Key::Char('m') => self.start_action(ActionId::Send, now),
            Key::Char('n') => self.start_action(ActionId::NewThread, now),
            _ => {}
        }
        Flow::Continue
    }

    /// Whether a lane's shown snapshot is older than its stale threshold.
    pub fn stale(&self, kind: LaneKind, age_ms: Option<u64>) -> bool {
        age_ms.is_none_or(|age| age > kind.timing().stale_after_ms)
    }

    /// Whether the lane's read has been in flight past the late threshold.
    pub fn late(&self, kind: LaneKind, now: Now) -> bool {
        self.lanes[&kind]
            .in_flight
            .as_ref()
            .is_some_and(|f| now.mono_ms.saturating_sub(f.started) > LATE_AFTER_MS)
    }
}

fn step<T: Clone + PartialEq>(items: &[T], current: Option<&T>, delta: i64) -> Option<T> {
    if items.is_empty() {
        return None;
    }
    let index = current
        .and_then(|c| items.iter().position(|i| i == c))
        .map_or(0, |i| {
            (i as i64 + delta).clamp(0, items.len() as i64 - 1) as usize
        });
    Some(items[index].clone())
}
