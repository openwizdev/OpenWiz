//! Strict versioned contract types, not source verification or notification policy.
//! Deserialize checks wire shape; `Document::check` checks local relationships.
//! Source authority, age, currentness and durable transitions require the runtime
//! proofs in notifications.v1.md. None of these types grants work authority.

use serde::{
    Deserialize, Deserializer, Serialize,
    de::{self, MapAccess, Visitor},
};
use std::{fmt, marker::PhantomData, num::NonZeroU64};

// Unlike derive, read only a map, require nullable keys, and reject duplicates.
macro_rules! object {
    ($name:ident { $($field:ident: $ty:ty),* $(,)? }) => {
        #[derive(Clone, Debug, PartialEq, Eq, Serialize)]
        pub struct $name { $(pub $field: $ty),* }
        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                struct ObjectVisitor;
                impl<'de> Visitor<'de> for ObjectVisitor {
                    type Value = $name;
                    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                        f.write_str(concat!("an exact ", stringify!($name), " object"))
                    }
                    fn visit_map<M: MapAccess<'de>>(self, mut m: M) -> Result<Self::Value, M::Error> {
                        $(let mut $field = None;)*
                        while let Some(key) = m.next_key::<String>()? {
                            match key.as_str() {
                                $(stringify!($field) => {
                                    if $field.is_some() { return Err(de::Error::duplicate_field(stringify!($field))); }
                                    $field = Some(m.next_value::<$ty>()?);
                                })*
                                _ => return Err(de::Error::custom(concat!("unknown field in ", stringify!($name)))),
                            }
                        }
                        Ok($name { $($field: $field.ok_or_else(|| de::Error::missing_field(stringify!($field)))?),* })
                    }
                }
                d.deserialize_map(ObjectVisitor)
            }
        }
    }
}
macro_rules! labels {
    ($name:ident { $($variant:ident => $wire:literal),+ $(,)? }) => {
        #[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
        pub enum $name { $(#[serde(rename = $wire)] $variant),+ }
        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                match String::deserialize(d)?.as_str() {
                    $($wire => Ok(Self::$variant),)+
                    _ => Err(de::Error::custom(concat!("unknown ", stringify!($name)))),
                }
            }
        }
    }
}
macro_rules! union {
    ($name:ident { $($variant:ident($ty:ty) => $wire:literal),+ $(,)? }) => {
        #[derive(Clone, Debug, PartialEq, Eq, Serialize)]
        pub enum $name { $(#[serde(rename = $wire)] $variant($ty)),+ }
        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                struct UnionVisitor;
                impl<'de> Visitor<'de> for UnionVisitor {
                    type Value = $name;
                    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("one named variant object") }
                    fn visit_map<M: MapAccess<'de>>(self, mut m: M) -> Result<Self::Value, M::Error> {
                        let key = m.next_key::<String>()?.ok_or_else(|| de::Error::custom("missing variant"))?;
                        let value = match key.as_str() {
                            $($wire => $name::$variant(m.next_value::<$ty>()?),)+
                            _ => return Err(de::Error::custom("unknown variant")),
                        };
                        if m.next_key::<String>()?.is_some() { return Err(de::Error::custom("extra variant key")); }
                        Ok(value)
                    }
                }
                d.deserialize_map(UnionVisitor)
            }
        }
    }
}
macro_rules! text_type {
    ($name:ident, $valid:expr) => {
        #[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);
        impl $name {
            pub fn new(value: impl Into<String>) -> Option<Self> {
                let value = value.into();
                ($valid)(&value).then_some(Self(value))
            }
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }
        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                Self::new(String::deserialize(d)?)
                    .ok_or_else(|| de::Error::custom(concat!("invalid ", stringify!($name))))
            }
        }
    };
}
text_type!(Text, |s: &str| !s.is_empty());
text_type!(Id, |s: &str| !s.is_empty()
    && s.len() <= 128
    && s.bytes()
        .next()
        .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'_')
    && s.bytes()
        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-')));
text_type!(RequestId, |s: &str| s
    .bytes()
    .next()
    .is_some_and(|b| b.is_ascii_alphanumeric())
    && s.bytes()
        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-')));
text_type!(Fingerprint, |s: &str| s.len() == 64
    && s.bytes().all(|b| matches!(b,b'0'..=b'9'|b'a'..=b'f')));
text_type!(OperationId, |s: &str| s.len() == 32
    && s.bytes().all(|b| matches!(b,b'0'..=b'9'|b'a'..=b'f')));
text_type!(Repository, |s: &str| {
    let Some((owner, name)) = s.split_once('/') else {
        return false;
    };
    !name.is_empty()
        && owner
            .bytes()
            .next()
            .is_some_and(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
        && owner
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        && name.bytes().all(|b| {
            b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'_' | b'-' | b'.')
        })
});

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Fact<T> {
    Known(T),
    Unknown(Text),
}
impl<'de, T: Deserialize<'de>> Deserialize<'de> for Fact<T> {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct FactVisitor<T>(PhantomData<T>);
        impl<'de, T: Deserialize<'de>> Visitor<'de> for FactVisitor<T> {
            type Value = Fact<T>;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("one known or unknown fact object")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut m: M) -> Result<Self::Value, M::Error> {
                let key = m
                    .next_key::<String>()?
                    .ok_or_else(|| de::Error::custom("missing fact"))?;
                let value = match key.as_str() {
                    "known" => Fact::Known(m.next_value()?),
                    "unknown" => Fact::Unknown(m.next_value()?),
                    _ => return Err(de::Error::custom("unknown fact kind")),
                };
                if m.next_key::<String>()?.is_some() {
                    return Err(de::Error::custom("extra fact key"));
                }
                Ok(value)
            }
        }
        d.deserialize_map(FactVisitor(PhantomData))
    }
}
labels!(SchemaId { V1 => "openwiz.notifications.v1" });
labels!(SourceOwner { Decisions=>"decisions",ServiceHealth=>"service_health",LoopWatchdog=>"loop_watchdog",EventRouter=>"event_router",Fleet=>"fleet",Inventory=>"inventory",Plan=>"plan",Loops=>"loops",ServiceUpdate=>"service_update" });
labels!(RecoverySource { ServiceHealth=>"service_health",LoopWatchdog=>"loop_watchdog" });
labels!(CoverageState { Complete=>"complete",Partial=>"partial" });
labels!(FreshnessState { Fresh=>"fresh",Stale=>"stale",Unknown=>"unknown" });
labels!(SubjectKind { Issue=>"issue",PullRequest=>"pull_request" });
labels!(RequestState { Open=>"open",Resolved=>"resolved",Superseded=>"superseded" });
labels!(IncidentState { Repairing=>"repairing",Escalated=>"escalated",Recovered=>"recovered" });
labels!(Risk { Ordinary=>"ordinary",Live=>"live",Release=>"release",Publish=>"publish",Unknown=>"unknown" });
labels!(Category { Decision=>"decision",RecoveryEscalation=>"recovery_escalation",CiFailed=>"ci_failed",ReviewFindings=>"review_findings",ReCheck=>"re_check",Merge=>"merge",AgentComplete=>"agent_complete",ReadyStockChanged=>"ready_stock_changed",LoopMissed=>"loop_missed",LoopStuck=>"loop_stuck",LoopDisabled=>"loop_disabled",LoopRunChanged=>"loop_run_changed",RecoveryChanged=>"recovery_changed",ServiceUpdate=>"service_update",ContractChanged=>"contract_changed",FleetWaitChanged=>"fleet_wait_changed" });
labels!(OptionalCategory { CiFailed=>"ci_failed",ReviewFindings=>"review_findings",ReCheck=>"re_check",Merge=>"merge",AgentComplete=>"agent_complete",ReadyStockChanged=>"ready_stock_changed",LoopMissed=>"loop_missed",LoopStuck=>"loop_stuck",LoopDisabled=>"loop_disabled",LoopRunChanged=>"loop_run_changed",RecoveryChanged=>"recovery_changed",ServiceUpdate=>"service_update",ContractChanged=>"contract_changed",FleetWaitChanged=>"fleet_wait_changed" });
labels!(CapabilityState { Unavailable=>"unavailable",Unsupported=>"unsupported",SetupRequired=>"setup_required",Ready=>"ready" });
labels!(Permission { Unknown=>"unknown",Prompt=>"prompt",Granted=>"granted",Denied=>"denied",Revoked=>"revoked",Unsupported=>"unsupported" });
labels!(SubscriptionState { Absent=>"absent",Ready=>"ready",Revoked=>"revoked",Failed=>"failed",Unsupported=>"unsupported" });
labels!(OutcomeState { Pending=>"pending",Accepted=>"accepted",Failed=>"failed",Uncertain=>"uncertain" });
labels!(DispatchState { Reserved=>"reserved",Submitting=>"submitting",Pending=>"pending",Accepted=>"accepted",Failed=>"failed",Uncertain=>"uncertain",Cancelled=>"cancelled" });
labels!(GroupState { Open=>"open",Closed=>"closed" });
labels!(StatusState { Off=>"off",Unavailable=>"unavailable",Unsupported=>"unsupported",SetupRequired=>"setup_required",PermissionDenied=>"permission_denied",PermissionRevoked=>"permission_revoked",Ready=>"ready",Pending=>"pending",Accepted=>"accepted",Failed=>"failed",Uncertain=>"uncertain" });
labels!(StockState { Fed=>"fed",LowStock=>"low_stock",RunningDry=>"running_dry",NoBuilders=>"no_builders",Indeterminate=>"indeterminate" });
labels!(TargetState { Current=>"current",Changed=>"changed",Resolved=>"resolved",Missing=>"missing",Ambiguous=>"ambiguous",Unread=>"unread" });
labels!(PayloadTitle { Attention=>"OpenWiz needs your attention" });

object!(Gap {
    source: SourceOwner,
    reason: Text
});
object!(Coverage { state:CoverageState,gaps:Vec<Gap> });
object!(Freshness { state:FreshnessState,snapshot_at:Fact<u64> });
object!(Subject {
    kind: SubjectKind,
    number: NonZeroU64
});
object!(DecisionRef {
    repository: Repository,
    subject: Subject,
    comment_id: NonZeroU64,
    request_id: RequestId,
    fingerprint: Fingerprint
});
object!(IncidentRef {
    repository: Repository,
    owner: Id,
    source: RecoverySource,
    subject: Id,
    incident: Id
});
object!(EventRef {
    repository: Repository,
    source: SourceOwner,
    subject: Id,
    event_id: Id,
    revision: Id
});
union!(Reference { Decision(DecisionRef)=>"decision",Incident(IncidentRef)=>"incident",Event(EventRef)=>"event" });
object!(DecisionFact { binding:DecisionRef,state:RequestState,current:Fact<bool>,risk:Risk,coverage:Coverage,freshness:Freshness });
object!(IncidentFact { binding:IncidentRef,state:IncidentState,owner_escalated:Fact<bool>,coverage:Coverage,freshness:Freshness });
object!(EventFact { binding:EventRef,category:OptionalCategory,current:Fact<bool>,coverage:Coverage,freshness:Freshness });
union!(SourceFact { Decision(DecisionFact)=>"decision",Incident(IncidentFact)=>"incident",Event(EventFact)=>"event" });
object!(Toggles {
    decision: bool,
    recovery_escalation: bool,
    ci_failed: bool,
    review_findings: bool,
    re_check: bool,
    merge: bool,
    agent_complete: bool,
    ready_stock_changed: bool,
    loop_missed: bool,
    loop_stuck: bool,
    loop_disabled: bool,
    loop_run_changed: bool,
    recovery_changed: bool,
    service_update: bool,
    contract_changed: bool,
    fleet_wait_changed: bool
});
object!(Preferences {
    generation: u64,
    enabled: bool,
    categories: Toggles
});
object!(PreferenceWrite {
    operation_id: OperationId,
    expected_generation: u64,
    enabled: bool,
    categories: Toggles
});
object!(Subscription { generation:u64,state:SubscriptionState,binding_id:Option<Id>,reason:Text,next:Text });
object!(SubscriptionWrite {
    operation_id: OperationId,
    expected_generation: u64,
    binding_id: Id
});
object!(Capability {
    state: CapabilityState,
    permission: Permission,
    reason: Text,
    next: Text
});
object!(DeliveryOutcome {
    state: OutcomeState,
    reason: Text
});
object!(ExternalPayload {
    title: PayloadTitle,
    target_token: Fingerprint
});
object!(Submission {
    dispatch_id: OperationId,
    group: Reference,
    preference_generation: u64,
    subscription_generation: u64,
    payload: ExternalPayload
});
object!(Dispatch { submission:Submission,state:DispatchState,group_state:GroupState,reserved_at:u64,updated_at:u64,outcome:Option<DeliveryOutcome> });
object!(CategoryStatus { category:Category,available:Fact<bool>,reason:Text });
object!(Status { state:StatusState,reason:Text,next:Text,preferences:Preferences,capability:Capability,subscription:Subscription,sources:Vec<CategoryStatus>,latest:Option<Dispatch>,coverage:Coverage,freshness:Freshness });
object!(StockCounts {
    ready: u64,
    running: u64,
    blocked: u64,
    held: u64,
    unapproved: u64,
    owner_wait: u64,
    capacity_wait: u64,
    unknown: u64,
    state: StockState
});
object!(StockSample {
    snapshot_at: u64,
    counts: StockCounts
});
object!(ProjectStock { project:Id,coverage:Coverage,freshness:Freshness,counts:Fact<StockCounts>,last_good:Option<StockSample> });
object!(Stock { coverage:Coverage,freshness:Freshness,projects:Vec<ProjectStock>,totals:Fact<StockCounts> });
object!(TargetResult {
    reference: Reference,
    state: TargetState,
    coverage: Coverage,
    freshness: Freshness
});
object!(RuntimeState { state:StatusState,preference_generation:u64,last_pass_at:Fact<u64>,reason:Text });
union!(Record { SourceFact(SourceFact)=>"source_fact",Preferences(Preferences)=>"preferences",PreferenceWrite(PreferenceWrite)=>"preference_write",Subscription(Subscription)=>"subscription",SubscriptionWrite(SubscriptionWrite)=>"subscription_write",Capability(Capability)=>"capability",Dispatch(Dispatch)=>"dispatch",Status(Box<Status>)=>"status",Stock(Stock)=>"stock",TargetResult(TargetResult)=>"target_result",Submission(Submission)=>"submission",DeliveryOutcome(DeliveryOutcome)=>"delivery_outcome" });
object!(Document {
    schema: SchemaId,
    record: Record
});

impl Category {
    pub const ALL: [Self; 16] = [
        Self::Decision,
        Self::RecoveryEscalation,
        Self::CiFailed,
        Self::ReviewFindings,
        Self::ReCheck,
        Self::Merge,
        Self::AgentComplete,
        Self::ReadyStockChanged,
        Self::LoopMissed,
        Self::LoopStuck,
        Self::LoopDisabled,
        Self::LoopRunChanged,
        Self::RecoveryChanged,
        Self::ServiceUpdate,
        Self::ContractChanged,
        Self::FleetWaitChanged,
    ];
}
impl Toggles {
    pub fn defaults() -> Self {
        Self {
            decision: true,
            recovery_escalation: true,
            ci_failed: false,
            review_findings: false,
            re_check: false,
            merge: false,
            agent_complete: false,
            ready_stock_changed: false,
            loop_missed: false,
            loop_stuck: false,
            loop_disabled: false,
            loop_run_changed: false,
            recovery_changed: false,
            service_update: false,
            contract_changed: false,
            fleet_wait_changed: false,
        }
    }
    pub fn enabled(&self, category: Category) -> bool {
        match category {
            Category::Decision => self.decision,
            Category::RecoveryEscalation => self.recovery_escalation,
            Category::CiFailed => self.ci_failed,
            Category::ReviewFindings => self.review_findings,
            Category::ReCheck => self.re_check,
            Category::Merge => self.merge,
            Category::AgentComplete => self.agent_complete,
            Category::ReadyStockChanged => self.ready_stock_changed,
            Category::LoopMissed => self.loop_missed,
            Category::LoopStuck => self.loop_stuck,
            Category::LoopDisabled => self.loop_disabled,
            Category::LoopRunChanged => self.loop_run_changed,
            Category::RecoveryChanged => self.recovery_changed,
            Category::ServiceUpdate => self.service_update,
            Category::ContractChanged => self.contract_changed,
            Category::FleetWaitChanged => self.fleet_wait_changed,
        }
    }
}
impl Preferences {
    pub fn off() -> Self {
        Self {
            generation: 0,
            enabled: false,
            categories: Toggles::defaults(),
        }
    }
}
fn text(value: &str) -> Text {
    Text::new(value).expect("nonempty contract text")
}
impl Capability {
    pub fn unavailable() -> Self {
        Self {
            state: CapabilityState::Unavailable,
            permission: Permission::Unknown,
            reason: text("Notification transport is not bound"),
            next: text("Establish the observed delivery binding before enabling delivery"),
        }
    }
}
impl Status {
    pub fn unavailable() -> Self {
        Self {
            state: StatusState::Off,
            reason: text("Delivery is off; transport is unavailable"),
            next: text("Establish the observed binding, then explicitly enable delivery"),
            preferences: Preferences::off(),
            capability: Capability::unavailable(),
            subscription: Subscription {
                generation: 0,
                state: SubscriptionState::Absent,
                binding_id: None,
                reason: text("No subscription is registered"),
                next: text("Explicit owner setup is required"),
            },
            sources: Category::ALL
                .into_iter()
                .map(|category| CategoryStatus {
                    category,
                    available: Fact::Unknown(text("Notification source binding is not installed")),
                    reason: text("Independent current source evidence is required"),
                })
                .collect(),
            latest: None,
            coverage: Coverage {
                state: CoverageState::Partial,
                gaps: vec![Gap {
                    source: SourceOwner::Decisions,
                    reason: text("Notification source binding is not installed"),
                }],
            },
            freshness: Freshness {
                state: FreshnessState::Unknown,
                snapshot_at: Fact::Unknown(text("No notification source pass has completed")),
            },
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TransitionCause {
    BeforeSubmit,
    BoundaryReply,
    BoundReconciliation,
}
impl DispatchState {
    /// Contract transition table only. Runtime must persist and serialize it.
    pub fn permits(self, next: Self, cause: TransitionCause) -> bool {
        use DispatchState::*;
        use TransitionCause::*;
        matches!(
            (self, next, cause),
            (Reserved, Submitting | Cancelled, BeforeSubmit)
                | (
                    Submitting,
                    Pending | Accepted | Failed | Uncertain,
                    BoundaryReply
                )
                | (Pending, Accepted | Failed | Uncertain, BoundaryReply)
                | (
                    Submitting | Pending | Uncertain,
                    Accepted | Failed,
                    BoundReconciliation
                )
        )
    }
}

type Check = Result<(), &'static str>;
impl Coverage {
    pub fn check(&self) -> Check {
        if (self.state == CoverageState::Complete) != self.gaps.is_empty() {
            Err("coverage and gaps disagree")
        } else {
            Ok(())
        }
    }
}
impl Freshness {
    pub fn check(&self) -> Check {
        if matches!(
            (&self.state, &self.snapshot_at),
            (FreshnessState::Unknown, Fact::Unknown(_))
                | (
                    FreshnessState::Fresh | FreshnessState::Stale,
                    Fact::Known(_)
                )
        ) {
            Ok(())
        } else {
            Err("freshness and snapshot disagree")
        }
    }
}
fn source_check(coverage: &Coverage, freshness: &Freshness) -> Check {
    coverage.check()?;
    freshness.check()?;
    if freshness.state == FreshnessState::Unknown && coverage.state == CoverageState::Complete {
        return Err("unknown required source timestamp needs a coverage gap");
    }
    Ok(())
}
fn fact_check<T>(fact: &Fact<T>, coverage: &Coverage) -> Check {
    if matches!(fact, Fact::Unknown(_)) && coverage.state == CoverageState::Complete {
        return Err("unknown required source fact needs a coverage gap");
    }
    Ok(())
}
impl StockCounts {
    pub fn check(&self) -> Check {
        // u128 avoids overflow when validating the existing twice-running rule.
        let state = if self.unknown > 0 {
            StockState::Indeterminate
        } else if self.ready == 0 {
            StockState::RunningDry
        } else if self.running == 0 {
            StockState::NoBuilders
        } else if u128::from(self.ready) >= 2 * u128::from(self.running) {
            StockState::Fed
        } else {
            StockState::LowStock
        };
        if self.state == state {
            Ok(())
        } else {
            Err("stock state disagrees with actual counts")
        }
    }
}
impl Dispatch {
    pub fn check(&self) -> Check {
        if self.updated_at < self.reserved_at {
            return Err("dispatch time precedes reservation");
        }
        let expected = match self.state {
            DispatchState::Reserved | DispatchState::Submitting | DispatchState::Cancelled => None,
            DispatchState::Pending => Some(OutcomeState::Pending),
            DispatchState::Accepted => Some(OutcomeState::Accepted),
            DispatchState::Failed => Some(OutcomeState::Failed),
            DispatchState::Uncertain => Some(OutcomeState::Uncertain),
        };
        if self.outcome.as_ref().map(|o| o.state) == expected {
            Ok(())
        } else {
            Err("dispatch and outcome disagree")
        }
    }
}
impl Stock {
    pub fn check(&self) -> Check {
        source_check(&self.coverage, &self.freshness)?;
        for (i, p) in self.projects.iter().enumerate() {
            if self.projects[..i]
                .iter()
                .any(|prior| prior.project == p.project)
            {
                return Err("duplicate stock project");
            }
            source_check(&p.coverage, &p.freshness)?;
            if p.freshness.state == FreshnessState::Fresh {
                fact_check(&p.counts, &p.coverage)?;
            }
            if p.coverage.state == CoverageState::Partial
                && self.coverage.state == CoverageState::Complete
            {
                return Err("factory coverage must reflect incomplete project facts");
            }
            if let Fact::Known(c) = &p.counts {
                c.check()?;
            }
            if let Some(sample) = &p.last_good {
                sample.counts.check()?;
            }
        }
        if let Fact::Known(total) = &self.totals {
            if self.coverage.state != CoverageState::Complete
                || self.freshness.state != FreshnessState::Fresh
            {
                return Err("incomplete or old factory cannot publish current totals");
            }
            let mut sums = [0u128; 8];
            for p in &self.projects {
                if p.coverage.state != CoverageState::Complete
                    || p.freshness.state != FreshnessState::Fresh
                {
                    return Err("project is incomplete or old");
                }
                let Fact::Known(c) = &p.counts else {
                    return Err("project count is unknown");
                };
                for (sum, n) in sums.iter_mut().zip([
                    c.ready,
                    c.running,
                    c.blocked,
                    c.held,
                    c.unapproved,
                    c.owner_wait,
                    c.capacity_wait,
                    c.unknown,
                ]) {
                    *sum += u128::from(n);
                }
            }
            total.check()?;
            if sums
                != [
                    total.ready,
                    total.running,
                    total.blocked,
                    total.held,
                    total.unapproved,
                    total.owner_wait,
                    total.capacity_wait,
                    total.unknown,
                ]
                .map(u128::from)
            {
                return Err("factory total does not equal its covered projects");
            }
        }
        Ok(())
    }
}
impl Document {
    /// Local consistency only. A caller must also verify source authority,
    /// snapshot age, full enumeration and the durable submit protocol.
    pub fn check(&self) -> Check {
        match &self.record {
            Record::SourceFact(SourceFact::Decision(f)) => {
                source_check(&f.coverage, &f.freshness)?;
                fact_check(&f.current, &f.coverage)
            }
            Record::SourceFact(SourceFact::Incident(f)) => {
                source_check(&f.coverage, &f.freshness)?;
                fact_check(&f.owner_escalated, &f.coverage)
            }
            Record::SourceFact(SourceFact::Event(f)) => {
                source_check(&f.coverage, &f.freshness)?;
                fact_check(&f.current, &f.coverage)
            }
            Record::Dispatch(d) => d.check(),
            Record::Stock(s) => s.check(),
            Record::Status(s) => {
                source_check(&s.coverage, &s.freshness)?;
                if s.sources.len() != Category::ALL.len()
                    || Category::ALL.iter().any(|category| {
                        s.sources
                            .iter()
                            .filter(|entry| entry.category == *category)
                            .count()
                            != 1
                    })
                {
                    return Err("category status must cover every category exactly once");
                }
                for source in &s.sources {
                    fact_check(&source.available, &s.coverage)?;
                }
                if let Some(d) = &s.latest {
                    d.check()?;
                }
                Ok(())
            }
            Record::TargetResult(t) => source_check(&t.coverage, &t.freshness),
            _ => Ok(()),
        }
    }
}

/// Durable logical identity, distinct from the exact comment navigation binding.
/// Optional event callers also include their Category when reserving a group.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GroupKey {
    Decision {
        repository: Repository,
        subject: Subject,
        request_id: RequestId,
        fingerprint: Fingerprint,
    },
    Incident(IncidentRef),
    Event(EventRef),
}
impl Reference {
    pub fn group_key(&self) -> GroupKey {
        match self {
            Self::Decision(d) => GroupKey::Decision {
                repository: d.repository.clone(),
                subject: d.subject.clone(),
                request_id: d.request_id.clone(),
                fingerprint: d.fingerprint.clone(),
            },
            Self::Incident(i) => GroupKey::Incident(i.clone()),
            Self::Event(e) => GroupKey::Event(e.clone()),
        }
    }
}
