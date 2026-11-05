//! Installed engine, injected current-source owner, protected state and delivery.
use openwiz_core::{
    notifications::{
        boundary::{DeliveryBoundary, UnavailableDelivery},
        grouping,
        model::*,
        policy,
    },
    ops::Clock,
};
use openwiz_store::notifications::{Error, Observation, Store, document, text};
use std::{
    collections::BTreeSet,
    sync::{Arc, Mutex},
    time::Instant,
};

pub struct Batch {
    pub observations: Vec<Observation>,
    pub sources: Vec<CategoryStatus>,
    pub coverage: Coverage,
    pub freshness: Freshness,
}
/// Production implementors must independently verify saved proposal/wording/risk,
/// configured target, provenance, lifecycle order and full enumeration. Recheck
/// repeats those reads at the exact immutable source, never echoes the input.
/// An unavailable verifier returns Err/unknown facts, never current=true.
pub trait Sources: Send + Sync {
    fn read(&self, deadline: Instant) -> Result<Batch, Error>;
    fn recheck(&self, original: &Observation, deadline: Instant) -> Result<Observation, Error>;
}
pub struct UnavailableSources;
impl Sources for UnavailableSources {
    fn read(&self, _: Instant) -> Result<Batch, Error> {
        let s = Status::unavailable();
        Ok(Batch {
            observations: vec![],
            sources: s.sources,
            coverage: s.coverage,
            freshness: s.freshness,
        })
    }
    fn recheck(&self, _: &Observation, _: Instant) -> Result<Observation, Error> {
        Err(Error::Unavailable)
    }
}
pub type BindingVerifier = Arc<dyn Fn(&Id, Instant) -> bool + Send + Sync>;

pub struct Engine {
    pub store: Store,
    sources: Arc<dyn Sources>,
    delivery: Mutex<Box<dyn DeliveryBoundary + Send>>,
    clock: Arc<dyn Clock>,
    binding: BindingVerifier,
}
impl Engine {
    pub fn new(
        store: Store,
        sources: Arc<dyn Sources>,
        delivery: Box<dyn DeliveryBoundary + Send>,
        clock: Arc<dyn Clock>,
        binding: BindingVerifier,
    ) -> Self {
        Self {
            store,
            sources,
            delivery: Mutex::new(delivery),
            clock,
            binding,
        }
    }
    pub fn unavailable(store: Store, clock: Arc<dyn Clock>) -> Self {
        Self::new(
            store,
            Arc::new(UnavailableSources),
            Box::new(UnavailableDelivery),
            clock,
            Arc::new(|_, _| false),
        )
    }
    fn now(&self) -> Result<u64, Error> {
        u64::try_from(self.clock.now().0).map_err(|_| Error::Unavailable)
    }
    pub fn run(&self, deadline: Instant) -> Result<(), Error> {
        let mut locked = self.store.lock()?;
        locked.recover()?;
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        let batch = match self.sources.read(deadline) {
            Ok(batch) => batch,
            Err(error) => {
                for source in &mut locked.state.sources {
                    source.available =
                        Fact::Unknown(text("Current notification source pass is unread"));
                    source.reason = text("Source verification failed; no new submission");
                }
                add_gap(
                    &mut locked.state,
                    SourceOwner::Decisions,
                    "Current notification source pass is unread",
                );
                locked.state.freshness = Freshness {
                    state: FreshnessState::Unknown,
                    snapshot_at: Fact::Unknown(text("No complete current source snapshot")),
                };
                locked.save()?;
                return Err(error);
            }
        };
        let mut status = Status::unavailable();
        status.sources = batch.sources.clone();
        status.coverage = batch.coverage.clone();
        status.freshness = batch.freshness.clone();
        document(Record::Status(Box::new(status)))
            .check()
            .map_err(|_| Error::Unavailable)?;
        let now = self.now()?;
        // Ambiguous copied comments/content are one logical group, zero admissions.
        let mut ambiguous = BTreeSet::new();
        for (i, o) in batch.observations.iter().enumerate() {
            if batch.observations[..i]
                .iter()
                .any(|p| grouping::key(&p.fact) == grouping::key(&o.fact) && p != o)
            {
                ambiguous.insert(grouping::key(&o.fact));
            }
        }
        locked.state.sources = batch.sources;
        locked.state.coverage = batch.coverage;
        locked.state.freshness = batch.freshness;
        let mut indices = BTreeSet::new();
        for observation in &batch.observations {
            if policy::fresh(&observation.fact, now) {
                indices.insert(locked.observe(observation, now)?);
            }
        }
        locked.save()?;
        for index in indices {
            if Instant::now() >= deadline {
                return Err(Error::Unavailable);
            }
            let group = &locked.state.groups[index];
            let original = group.observation.clone();
            let available = locked.state.sources.iter().any(|s| {
                s.category == policy::category(&original.fact) && s.available == Fact::Known(true)
            });
            if ambiguous.contains(&group.key) || group.invalidated {
                add_gap(
                    &mut locked.state,
                    source_owner(&original.fact),
                    "Ambiguous or changed source binding refused under the same logical identity",
                );
                locked.save()?;
                continue;
            }
            if group.closed
                || !available
                || !policy::eligible(&original.fact, &locked.state.preferences, self.now()?)
                || group
                    .dispatch
                    .as_ref()
                    .is_some_and(|d| d.state != DispatchState::Reserved)
            {
                continue;
            }
            let mut delivery = self.delivery.lock().map_err(|_| Error::Unavailable)?;
            let ready = |cap: &Capability| {
                cap.state == CapabilityState::Ready && cap.permission == Permission::Granted
            };
            let subscription = locked.state.subscription.clone();
            if !ready(&delivery.capability())
                || subscription.state != SubscriptionState::Ready
                || subscription
                    .binding_id
                    .as_ref()
                    .is_none_or(|id| !(self.binding)(id, deadline))
            {
                continue;
            }
            let reserved = match locked.state.groups[index].dispatch.clone() {
                Some(d) => d,
                None => locked
                    .reserve(index, self.now()?)?
                    .ok_or(Error::Unavailable)?,
            };
            let checked = self.sources.recheck(&original, deadline);
            let valid = checked.as_ref().is_ok_and(|current| {
                openwiz_store::notifications::same_binding(current, &original)
                    && policy::source_time(&current.fact) >= policy::source_time(&original.fact)
                    && policy::eligible(
                        &current.fact,
                        &locked.state.preferences,
                        self.now().unwrap_or(u64::MAX),
                    )
            });
            if let Ok(current) = &checked
                && policy::fresh(&current.fact, self.now()?)
                && policy::closed(&current.fact)
            {
                locked.observe(current, self.now()?)?;
            }
            if !valid
                || locked.state.groups[index].closed
                || locked.state.preferences.generation != reserved.submission.preference_generation
                || locked.state.subscription.generation
                    != reserved.submission.subscription_generation
                || locked.state.subscription.state != SubscriptionState::Ready
                || !ready(&delivery.capability())
                || locked
                    .state
                    .subscription
                    .binding_id
                    .as_ref()
                    .is_none_or(|id| !(self.binding)(id, deadline))
                || Instant::now() >= deadline
            {
                if !valid && !checked.as_ref().is_ok_and(|o| policy::closed(&o.fact)) {
                    add_gap(
                        &mut locked.state,
                        source_owner(&original.fact),
                        "Current source binding changed or could not be independently verified; reservation cancelled",
                    );
                }
                locked.transition(
                    index,
                    DispatchState::Cancelled,
                    None,
                    TransitionCause::BeforeSubmit,
                    self.now()?,
                )?;
                continue;
            }
            // The store lock remains held through this boundary; preference or
            // subscription writes cannot overtake an admitted effect.
            locked.transition(
                index,
                DispatchState::Submitting,
                None,
                TransitionCause::BeforeSubmit,
                self.now()?,
            )?;
            let reply = delivery.submit(&reserved.submission);
            let state = match reply.state {
                OutcomeState::Pending => DispatchState::Pending,
                OutcomeState::Accepted => DispatchState::Accepted,
                OutcomeState::Failed => DispatchState::Failed,
                OutcomeState::Uncertain => DispatchState::Uncertain,
            };
            // Never persist raw provider diagnostics, endpoints, keys or wording.
            let reason = match reply.state {
                OutcomeState::Pending => "Dispatch pending; phone receipt is unverified",
                OutcomeState::Accepted => "Dispatch accepted; phone receipt is unverified",
                OutcomeState::Failed => "This dispatch was positively refused; no automatic retry",
                OutcomeState::Uncertain => "Dispatch outcome is unknown; no automatic retry",
            };
            locked.transition(
                index,
                state,
                Some(DeliveryOutcome {
                    state: reply.state,
                    reason: text(reason),
                }),
                TransitionCause::BoundaryReply,
                self.now()?,
            )?;
        }
        Ok(())
    }
}

impl openwiz_server::notifications::Api for Engine {
    fn read(
        &self,
        route: openwiz_server::notifications::Read,
        now: u64,
        deadline: Instant,
    ) -> Result<Document, Error> {
        use openwiz_server::notifications::Read;
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        let state = self.store.read()?;
        match route {
            Read::Preferences => Ok(document(Record::Preferences(state.preferences))),
            Read::Subscription => Ok(document(Record::Subscription(state.subscription))),
            Read::Status => {
                let raw = self
                    .delivery
                    .lock()
                    .map_err(|_| Error::Unavailable)?
                    .capability();
                let capability = safe_capability(raw);
                let mut status = Status::unavailable();
                status.latest = state.latest();
                status.preferences = state.preferences;
                status.subscription = state.subscription;
                status.sources = state.sources;
                status.coverage = state.coverage;
                status.freshness =
                    openwiz_core::notifications::stock::freshness(state.freshness.snapshot_at, now);
                status.capability = capability;
                status.state = if !status.preferences.enabled {
                    StatusState::Off
                } else if status.capability.state == CapabilityState::Unavailable {
                    StatusState::Unavailable
                } else if status.capability.state == CapabilityState::Unsupported
                    || status.capability.permission == Permission::Unsupported
                {
                    StatusState::Unsupported
                } else if status.capability.permission == Permission::Denied {
                    StatusState::PermissionDenied
                } else if status.capability.permission == Permission::Revoked {
                    StatusState::PermissionRevoked
                } else if status.capability.state != CapabilityState::Ready
                    || status.capability.permission != Permission::Granted
                    || status.subscription.state != SubscriptionState::Ready
                    || status
                        .subscription
                        .binding_id
                        .as_ref()
                        .is_none_or(|id| !(self.binding)(id, deadline))
                {
                    StatusState::SetupRequired
                } else if let Some(d) = &status.latest {
                    match d.state {
                        DispatchState::Pending => StatusState::Pending,
                        DispatchState::Accepted => StatusState::Accepted,
                        DispatchState::Failed => StatusState::Failed,
                        DispatchState::Submitting | DispatchState::Uncertain => {
                            StatusState::Uncertain
                        }
                        _ => StatusState::Ready,
                    }
                } else {
                    StatusState::Ready
                };
                status.reason = text(match status.state {
                    StatusState::Off => {
                        "Delivery is off; already submitted effects cannot be retracted"
                    }
                    StatusState::Accepted => "Dispatch accepted; phone receipt is unverified",
                    StatusState::Pending => "Dispatch pending; no automatic retry",
                    StatusState::Uncertain => "Dispatch outcome unknown; no automatic retry",
                    StatusState::Failed => "This dispatch was positively refused",
                    StatusState::Ready => {
                        "Current delivery prerequisites verified; phone receipt is unverified"
                    }
                    _ => "Delivery prerequisites are unavailable or need owner setup",
                });
                status.next = text(
                    "Review source gaps and current choices; preferences grant no work approval",
                );
                Ok(document(Record::Status(Box::new(status))))
            }
        }
    }
    fn write(
        &self,
        request: Document,
        remove: bool,
        now: u64,
        deadline: Instant,
    ) -> Result<Document, Error> {
        // A bounded local admission wait; the same durable operation survives a
        // lost HTTP reply. No provider call or CloudRoom work effect occurs here.
        loop {
            if Instant::now() >= deadline {
                return Err(Error::Busy);
            }
            let result = match &request.record {
                Record::PreferenceWrite(w) if !remove => self
                    .store
                    .write_preferences(w, now)
                    .map(|p| document(Record::Preferences(p))),
                Record::SubscriptionWrite(w) => self
                    .store
                    .write_subscription(w, remove, now, |id| (self.binding)(id, deadline))
                    .map(|s| document(Record::Subscription(s))),
                _ => return Err(Error::Unavailable),
            };
            if result != Err(Error::Busy) {
                return result;
            }
            std::thread::sleep(
                std::time::Duration::from_millis(5)
                    .min(deadline.saturating_duration_since(Instant::now())),
            );
        }
    }
}
fn safe_capability(raw: Capability) -> Capability {
    Capability {
        state: raw.state,
        permission: raw.permission,
        reason: text(
            "Delivery capability reflects current adapter prerequisites, never phone receipt",
        ),
        next: text("Explicit owner setup is required when prerequisites are unavailable"),
    }
}

fn source_owner(fact: &SourceFact) -> SourceOwner {
    match fact {
        SourceFact::Decision(_) => SourceOwner::Decisions,
        SourceFact::Incident(i) => match i.binding.source {
            RecoverySource::ServiceHealth => SourceOwner::ServiceHealth,
            RecoverySource::LoopWatchdog => SourceOwner::LoopWatchdog,
        },
        SourceFact::Event(e) => e.binding.source,
    }
}
fn add_gap(state: &mut openwiz_store::notifications::State, source: SourceOwner, reason: &str) {
    state.coverage.state = CoverageState::Partial;
    let gap = Gap {
        source,
        reason: text(reason),
    };
    if !state.coverage.gaps.contains(&gap) {
        state.coverage.gaps.push(gap);
    }
}
