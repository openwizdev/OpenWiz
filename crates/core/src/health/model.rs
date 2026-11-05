//! The health planner's types (T3, ClosedWiz#268): what a health pass sees,
//! and the parts of `contracts/service.v1.md` it works out: its results,
//! the fixes due, the "Needs you" items and the open incidents. **Data
//! only.** Printing a result, a fix, a pass or an incident gives the
//! contract's JSON (`contracts/service.v1.schema.json`).
//!
//! Each check has its own types, so no value holds a way of being broken,
//! a fix or an outcome that belongs to another check. Text that must not be
//! empty is a [`NonEmpty`], and an id an [`Id`]. These types only print:
//! anything read from outside goes through a hand-written strict reader
//! first (the contract, "Reading it").

use std::fmt;
use std::num::NonZeroU64;

use serde::{Serialize, Serializer};

pub use crate::fleet::model::NonEmpty;
use crate::messaging::OpId;
use crate::model::Timestamp;

/// A GitHub issue's number (a spec's), or a comment's id: 1 or more.
pub type Number = NonZeroU64;

/// A CloudRoom id (a loop's or a thread's): 1 to 128 ASCII letters,
/// digits, `_` or `-`, not starting with `-` (the adapter's rule).
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct Id(String);

impl Id {
    /// The longest id there is.
    pub const MAX_LEN: usize = 128;

    /// `id`, only when it keeps the rule.
    pub fn parse(id: &str) -> Option<Self> {
        let valid = !id.is_empty()
            && id.len() <= Self::MAX_LEN
            && !id.starts_with('-')
            && id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
        valid.then(|| Self(id.to_owned()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// The repository the fleets run on, as the config names it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Repository {
    owner: String,
    name: String,
}

impl Repository {
    /// `owner/name`, only when each keeps the config's rule: an owner is
    /// ASCII letters, digits and `-`, starting with a letter or digit; a
    /// name is ASCII letters, digits, `-`, `_` and `.`; neither is empty.
    pub fn parse(owner: &str, name: &str) -> Option<Self> {
        let owner_ok = owner
            .bytes()
            .next()
            .is_some_and(|b| b.is_ascii_alphanumeric())
            && owner
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-');
        let name_ok = !name.is_empty()
            && name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'));
        (owner_ok && name_ok).then(|| Self {
            owner: owner.to_owned(),
            name: name.to_owned(),
        })
    }
}

impl fmt::Display for Repository {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}/{}", self.owner, self.name)
    }
}

/// What a check couldn't read: the inventory's eight gap kinds, and
/// `cloudroom_not_running`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Gap {
    UntestedVersion,
    CommandFailed,
    TimedOut,
    BudgetExhausted,
    Malformed,
    MissingField,
    WrongType,
    NotFound,
    CloudroomNotRunning,
}

/// A gap and OpenWiz's own words for it: an `unread` result, or an
/// `unknown` observation.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Unread {
    pub gap: Gap,
    pub reason: NonEmpty,
}

// What a health pass sees: the planner's input.

/// What one health pass found, before any rule is applied. The executor
/// (T5) reads it; the planner works out every result from it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Seen {
    /// Whether the CloudRoom adapter found the running app's `room-cli`.
    pub cloudroom: CloudRoomSeen,
    /// Every loop in `room-cli loop list`, OpenWiz's or not: the planner
    /// keeps only OpenWiz's.
    pub loops: Listed<SeenLoop>,
    /// When the service's tick run going now started, if one is going.
    pub tick_running_since: Option<Timestamp>,
    /// Each open spec whose GitHub records name its fleet thread, and what
    /// `room-cli thread show` said of that thread.
    pub fleet_threads: Listed<SeenFleetThread>,
    /// What the server's health route answered.
    pub server: Known<ServerBroken>,
}

/// Whether the CloudRoom adapter found the running app's `room-cli`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CloudRoomSeen {
    Running,
    NotRunning,
}

/// A list a check reads: read in full, or not.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Listed<T> {
    Read(Vec<T>),
    Unread(Unread),
}

/// One loop in `room-cli loop list`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SeenLoop {
    pub id: Id,
    pub name: String,
    pub paused: bool,
}

/// One open spec's fleet thread, as its GitHub records name it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SeenFleetThread {
    pub spec: Number,
    pub thread: Id,
    pub seen: ThreadSeen,
}

/// What `room-cli thread show <id>` said of a fleet thread.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ThreadSeen {
    /// It exists and isn't archived.
    Present,
    /// CloudRoom says there is no such thread.
    NotFound,
    /// It is archived.
    Archived,
    /// It couldn't be read.
    Unknown(Unread),
}

/// The config's values the planner applies.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rules {
    /// The repository OpenWiz's loops name.
    pub repository: Repository,
    /// The tick's schedule, `tick.every_s`.
    pub tick_every_s: NonZeroU64,
}

// The ways each check can be broken.

/// A loop's way of being broken.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "what", rename_all = "snake_case")]
pub enum LoopBroken {
    Paused,
}

/// The tick's way of being broken.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "what", rename_all = "snake_case")]
pub enum TickBroken {
    /// A run is still going when the next run is due.
    Stalled { run_started_at: Timestamp },
}

/// A fleet thread's ways of being broken.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "what", rename_all = "snake_case")]
pub enum FleetThreadBroken {
    NotFound,
    Archived,
}

/// The server's ways of being broken.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "what", rename_all = "snake_case")]
pub enum ServerBroken {
    Refused,
    TimedOut,
    WrongAnswer,
}

/// CloudRoom's way of being broken.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "what", rename_all = "snake_case")]
pub enum CloudRoomBroken {
    NotRunning,
}

/// An observation of a subject that can't be unknown: `tick`, `server` and
/// `cloudroom`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Known<B> {
    Healthy,
    Broken(B),
}

/// An observation of a subject read through `room-cli`: `loop` and
/// `fleet_thread`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Observed<B> {
    Healthy,
    Broken(B),
    Unknown(Unread),
}

// A health pass's output.

/// One of OpenWiz's loops: its id and its name.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Loop {
    pub id: Id,
    pub name: NonEmpty,
}

/// One subject's result in a pass, or a check's one `unread` result.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "check", rename_all = "snake_case")]
pub enum CheckResult {
    Loop(LoopResult),
    Tick {
        observed: Known<TickBroken>,
    },
    FleetThread(FleetThreadResult),
    Server {
        observed: Known<ServerBroken>,
    },
    #[serde(rename = "cloudroom")]
    CloudRoom {
        observed: Known<CloudRoomBroken>,
    },
}

/// A `loop` result: one loop's, or the check's `unread`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum LoopResult {
    Seen {
        #[serde(rename = "loop")]
        subject: Loop,
        observed: Observed<LoopBroken>,
    },
    Unread {
        unread: Unread,
    },
}

/// A `fleet_thread` result: one spec's fleet thread's, or the check's
/// `unread`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum FleetThreadResult {
    Seen {
        spec: Number,
        thread: Id,
        observed: Observed<FleetThreadBroken>,
    },
    Unread {
        unread: Unread,
    },
}

/// A fix's try: the first or the second. There is no third.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Try {
    First,
    Second,
}

impl Serialize for Try {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_u8(match self {
            Self::First => 1,
            Self::Second => 2,
        })
    }
}

/// An incident's id: `i` and then its number.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct IncidentId(pub Number);

impl fmt::Display for IncidentId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "i{}", self.0)
    }
}

impl Serialize for IncidentId {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

/// A fix that is due: one try of one fix, for one incident.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "fix", rename_all = "snake_case")]
pub enum Fix {
    /// `room-cli loop resume <id>`.
    ResumeLoop {
        incident: IncidentId,
        #[serde(rename = "try")]
        attempt: Try,
        #[serde(rename = "loop")]
        subject: Loop,
    },
    /// Stop the stalled run, then start a new one.
    RestartTick {
        incident: IncidentId,
        #[serde(rename = "try")]
        attempt: Try,
    },
    /// Start a new fleet thread for `spec`, which takes over from its
    /// GitHub records. `thread` is the one that is gone.
    TakeOverFleetThread {
        incident: IncidentId,
        #[serde(rename = "try")]
        attempt: Try,
        spec: Number,
        thread: Id,
    },
    /// Stop the service's server, then start it again with the same config.
    RestartServer {
        incident: IncidentId,
        #[serde(rename = "try")]
        attempt: Try,
    },
}

// The incidents: the planner's part of the service's state.

/// How a try went: `resume_loop`'s, `restart_tick`'s and
/// `restart_server`'s.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Outcome {
    Done,
    Failed { gap: Gap, reason: NonEmpty },
    Interrupted,
}

/// How a takeover went: `take_over_fleet_thread`'s, which names the new
/// fleet thread when it is done.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum TakeoverOutcome {
    Done {
        thread: Id,
    },
    /// TK1: the registered service tick owns the fleet; no agent was created.
    #[serde(rename = "done")]
    ServiceTick {
        owner: ServiceTickOwner,
        retired_loop: Id,
    },
    Failed {
        gap: Gap,
        reason: NonEmpty,
    },
    Interrupted,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ServiceTickOwner {
    ServiceTick,
}

/// One saved try. `outcome` is `None` only while its command runs;
/// `comment` is `None` until its record's comment id is saved.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct SavedTry<O> {
    pub at: Timestamp,
    pub outcome: Option<O>,
    pub comment: Option<Number>,
}

/// An incident's tries: none yet, the first, or both. A second never comes
/// without a first, and there is no third.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Tries<O> {
    Zero,
    One(SavedTry<O>),
    Two(SavedTry<O>, SavedTry<O>),
}

impl<O> Tries<O> {
    /// The latest try, for the executor to save its outcome and comment id.
    pub fn last_mut(&mut self) -> Option<&mut SavedTry<O>> {
        match self {
            Self::Zero => None,
            Self::One(last) | Self::Two(_, last) => Some(last),
        }
    }
}

impl<O: Serialize> Serialize for Tries<O> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        #[derive(Serialize)]
        struct Both<'a, O> {
            first: Option<&'a SavedTry<O>>,
            second: Option<&'a SavedTry<O>>,
        }
        let (first, second) = match self {
            Self::Zero => (None, None),
            Self::One(first) => (Some(first), None),
            Self::Two(first, second) => (Some(first), Some(second)),
        };
        Both { first, second }.serialize(serializer)
    }
}

/// An incident's "Needs you", saved with its `send` op id before its
/// comment and its message. `comment` is `None` until its comment id is
/// saved.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct NeedsYou {
    pub at: Timestamp,
    pub op_id: OpId,
    pub comment: Option<Number>,
}

/// What an incident is about: its check, its subject, its latest broken
/// observation and its fix's tries. `cloudroom` has no fix, so no tries.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "check", rename_all = "snake_case")]
pub enum Fault {
    Loop {
        #[serde(rename = "loop")]
        subject: Loop,
        #[serde(serialize_with = "as_broken")]
        broken: LoopBroken,
        tries: Tries<Outcome>,
    },
    Tick {
        #[serde(serialize_with = "as_broken")]
        broken: TickBroken,
        tries: Tries<Outcome>,
    },
    FleetThread {
        spec: Number,
        /// The fleet thread last found gone.
        thread: Id,
        #[serde(serialize_with = "as_broken")]
        broken: FleetThreadBroken,
        tries: Tries<TakeoverOutcome>,
    },
    Server {
        #[serde(serialize_with = "as_broken")]
        broken: ServerBroken,
        tries: Tries<Outcome>,
    },
    #[serde(rename = "cloudroom")]
    CloudRoom {
        #[serde(serialize_with = "as_broken")]
        broken: CloudRoomBroken,
    },
}

/// A broken way, printed as its broken observation.
fn as_broken<B: Serialize, S: Serializer>(broken: &B, serializer: S) -> Result<S::Ok, S::Error> {
    Known::Broken(broken).serialize(serializer)
}

/// One subject's fault, from its first broken result to its end.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Incident {
    pub id: IncidentId,
    #[serde(flatten)]
    pub fault: Fault,
    pub opened_at: Timestamp,
    /// When it was first seen healthy since it was last broken.
    pub healthy_since: Option<Timestamp>,
    pub needs_you: Option<NeedsYou>,
}

/// The open incidents, and the next incident's number: the planner's part
/// of `service/state.json`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Incidents {
    pub next_incident: Number,
    pub incidents: Vec<Incident>,
}

impl Default for Incidents {
    /// None open, and the first is `i1`.
    fn default() -> Self {
        Self {
            next_incident: Number::MIN,
            incidents: Vec::new(),
        }
    }
}

/// One health pass: a result for each subject, the fixes it made due, and
/// the incidents it made a "Needs you" due for. The status's and the
/// state's `last_pass`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Pass {
    pub at: Timestamp,
    pub results: Vec<CheckResult>,
    pub fixes: Vec<Fix>,
    pub needs_you: Vec<IncidentId>,
}

/// What the planner returns: the pass, and the incidents after it, with
/// each due try and "Needs you" already saved in them.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Plan {
    pub pass: Pass,
    pub incidents: Incidents,
}
