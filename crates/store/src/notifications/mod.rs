//! One protected owner journal and lock shared by engine admission and API writes.
//! No provider calls, source reads, or work effects. Missing state is unavailable.
mod storage;
use openwiz_core::notifications::{grouping, model::*, policy};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
};
pub use storage::Locked;

#[derive(Clone)]
pub struct Store {
    root: PathBuf,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Unavailable,
    Busy,
    OperationConflict,
    GenerationConflict,
    SubscriptionUnavailable,
}

/// Supplied only by the independently verifying source owner. The content binding
/// covers exact saved wording/question/summary/headline, risk and configured target,
/// at its immutable source revision. It is not a request's self-asserted hash.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub fact: SourceFact,
    pub content_binding: Fingerprint,
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Group {
    pub key: Vec<u8>,
    pub observation: Observation,
    pub closed: bool,
    pub invalidated: bool,
    pub snapshot_at: u64,
    pub dispatch: Option<Dispatch>,
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    request: Document,
    result: Document,
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    schema: String,
    pub preferences: Preferences,
    pub subscription: Subscription,
    pub groups: Vec<Group>,
    receipts: Vec<Receipt>,
    pub sources: Vec<CategoryStatus>,
    pub coverage: Coverage,
    pub freshness: Freshness,
}
impl State {
    fn initial() -> Self {
        let status = Status::unavailable();
        Self {
            schema: "openwiz.notification-state.v1".into(),
            preferences: status.preferences,
            subscription: status.subscription,
            groups: vec![],
            receipts: vec![],
            sources: status.sources,
            coverage: status.coverage,
            freshness: status.freshness,
        }
    }
    fn check(&self) -> Result<(), Error> {
        if self.schema != "openwiz.notification-state.v1" {
            return Err(Error::Unavailable);
        }
        let mut keys = BTreeSet::new();
        let mut dispatches = BTreeSet::new();
        let mut tokens = BTreeSet::new();
        for group in &self.groups {
            let fact = &group.observation.fact;
            document(Record::SourceFact(fact.clone()))
                .check()
                .map_err(|_| Error::Unavailable)?;
            if grouping::key(fact) != group.key
                || policy::source_time(fact).is_none_or(|t| t > group.snapshot_at)
                || !keys.insert(group.key.clone())
            {
                return Err(Error::Unavailable);
            }
            if let Some(d) = &group.dispatch {
                d.check().map_err(|_| Error::Unavailable)?;
                if d.submission.group != policy::reference(fact)
                    || (d.group_state == GroupState::Closed) != group.closed
                    || !dispatches.insert(d.submission.dispatch_id.clone())
                    || !tokens.insert(d.submission.payload.target_token.clone())
                    || d.submission.preference_generation > self.preferences.generation
                    || d.submission.subscription_generation > self.subscription.generation
                {
                    return Err(Error::Unavailable);
                }
            }
        }
        if (self.subscription.state == SubscriptionState::Ready)
            != self.subscription.binding_id.is_some()
        {
            return Err(Error::Unavailable);
        }
        let mut operations = BTreeSet::new();
        for receipt in &self.receipts {
            receipt.request.check().map_err(|_| Error::Unavailable)?;
            receipt.result.check().map_err(|_| Error::Unavailable)?;
            let id = match (&receipt.request.record, &receipt.result.record) {
                (Record::PreferenceWrite(w), Record::Preferences(p))
                    if w.expected_generation.checked_add(1) == Some(p.generation)
                        && p.generation <= self.preferences.generation
                        && w.enabled == p.enabled
                        && w.categories == p.categories =>
                {
                    &w.operation_id
                }
                (Record::SubscriptionWrite(w), Record::Subscription(s))
                    if w.expected_generation.checked_add(1) == Some(s.generation)
                        && s.generation <= self.subscription.generation =>
                {
                    &w.operation_id
                }
                _ => return Err(Error::Unavailable),
            };
            if !operations.insert(id.clone()) {
                return Err(Error::Unavailable);
            }
        }
        let mut status = Status::unavailable();
        status.sources = self.sources.clone();
        status.coverage = self.coverage.clone();
        status.freshness = self.freshness.clone();
        document(Record::Status(Box::new(status)))
            .check()
            .map_err(|_| Error::Unavailable)
    }
    fn prior(&self, request: &Document) -> Result<Option<Document>, Error> {
        let id = operation(request)?;
        for receipt in &self.receipts {
            if operation(&receipt.request)? == id {
                return if receipt.request == *request {
                    Ok(Some(receipt.result.clone()))
                } else {
                    Err(Error::OperationConflict)
                };
            }
        }
        Ok(None)
    }
    fn cancel_reservations(&mut self, now: u64) {
        for group in &mut self.groups {
            if let Some(d) = &mut group.dispatch
                && d.state == DispatchState::Reserved
            {
                d.state = DispatchState::Cancelled;
                d.updated_at = d.updated_at.max(now);
            }
        }
    }
    pub fn latest(&self) -> Option<Dispatch> {
        self.groups
            .iter()
            .filter_map(|g| g.dispatch.as_ref())
            .max_by_key(|d| {
                (
                    matches!(
                        d.state,
                        DispatchState::Submitting
                            | DispatchState::Pending
                            | DispatchState::Uncertain
                    ),
                    d.reserved_at,
                    d.updated_at,
                )
            })
            .cloned()
            .map(recovered)
    }
}

pub fn document(record: Record) -> Document {
    Document {
        schema: SchemaId::V1,
        record,
    }
}
fn operation(document: &Document) -> Result<&OperationId, Error> {
    match &document.record {
        Record::PreferenceWrite(w) => Ok(&w.operation_id),
        Record::SubscriptionWrite(w) => Ok(&w.operation_id),
        _ => Err(Error::Unavailable),
    }
}
pub fn text(value: &str) -> Text {
    Text::new(value).expect("static nonempty notification text")
}

fn recovered(mut dispatch: Dispatch) -> Dispatch {
    if dispatch.state == DispatchState::Submitting {
        dispatch.state = DispatchState::Uncertain;
        dispatch.outcome = Some(DeliveryOutcome {
            state: OutcomeState::Uncertain,
            reason: text("Submission outcome is unknown; no automatic retry"),
        });
    }
    dispatch
}

impl Store {
    pub fn new(root: &Path) -> Self {
        Self {
            root: root.to_owned(),
        }
    }
    pub fn initialize(&self) -> Result<(), Error> {
        storage::initialize(&self.root)
    }
    pub fn lock(&self) -> Result<Locked, Error> {
        storage::open(&self.root, false)
    }
    pub fn read(&self) -> Result<State, Error> {
        Ok(storage::open(&self.root, true)?.state.clone())
    }
    pub fn preferences(&self) -> Result<Preferences, Error> {
        Ok(self.read()?.preferences)
    }
    pub fn write_preferences(
        &self,
        write: &PreferenceWrite,
        now: u64,
    ) -> Result<Preferences, Error> {
        let mut locked = self.lock()?;
        let request = document(Record::PreferenceWrite(write.clone()));
        if let Some(prior) = locked.state.prior(&request)? {
            let Record::Preferences(p) = prior.record else {
                return Err(Error::Unavailable);
            };
            return Ok(p);
        }
        if locked.state.preferences.generation != write.expected_generation {
            return Err(Error::GenerationConflict);
        }
        let generation = write
            .expected_generation
            .checked_add(1)
            .ok_or(Error::Unavailable)?;
        let result = Preferences {
            generation,
            enabled: write.enabled,
            categories: write.categories.clone(),
        };
        locked.state.preferences = result.clone();
        locked.state.cancel_reservations(now);
        locked.state.receipts.push(Receipt {
            request,
            result: document(Record::Preferences(result.clone())),
        });
        locked.save()?;
        Ok(result)
    }
    /// Binding verification is supplied by T4's observed adapter, under this same
    /// admission lock. This closure never provisions a provider resource.
    pub fn write_subscription(
        &self,
        write: &SubscriptionWrite,
        remove: bool,
        now: u64,
        verify: impl FnOnce(&Id) -> bool,
    ) -> Result<Subscription, Error> {
        let mut locked = self.lock()?;
        // DELETE and PUT must have different canonical identities even though
        // the pinned wire record is the same. Receipt results carry the method.
        let request = document(Record::SubscriptionWrite(write.clone()));
        if let Some(prior) = locked.state.prior(&request)? {
            let Record::Subscription(s) = prior.record else {
                return Err(Error::Unavailable);
            };
            if (s.state == SubscriptionState::Revoked) != remove {
                return Err(Error::OperationConflict);
            }
            return Ok(s);
        }
        let old = &locked.state.subscription;
        if old.generation != write.expected_generation {
            return Err(Error::GenerationConflict);
        }
        if remove {
            if old.binding_id.as_ref() != Some(&write.binding_id) {
                return Err(Error::SubscriptionUnavailable);
            }
        } else if !verify(&write.binding_id) {
            return Err(Error::SubscriptionUnavailable);
        }
        let generation = old.generation.checked_add(1).ok_or(Error::Unavailable)?;
        let result = Subscription {
            generation,
            state: if remove {
                SubscriptionState::Revoked
            } else {
                SubscriptionState::Ready
            },
            binding_id: if remove {
                None
            } else {
                Some(write.binding_id.clone())
            },
            reason: text(if remove {
                "Local binding removed; already submitted effects cannot be retracted"
            } else {
                "Protected binding verified; this does not prove phone receipt"
            }),
            next: text(if remove {
                "Provider cleanup requires its separately observed flow"
            } else {
                "Current permission and owner enable are still required"
            }),
        };
        locked.state.subscription = result.clone();
        locked.state.cancel_reservations(now);
        locked.state.receipts.push(Receipt {
            request,
            result: document(Record::Subscription(result.clone())),
        });
        locked.save()?;
        Ok(result)
    }
    /// T5's only durable token mapping. No writes, fallback item, or source authority.
    pub fn target(&self, token: &Fingerprint) -> Result<Option<Observation>, Error> {
        let state = self.read()?;
        Ok(state
            .groups
            .iter()
            .find(|g| {
                g.dispatch
                    .as_ref()
                    .is_some_and(|d| &d.submission.payload.target_token == token)
            })
            .map(|g| g.observation.clone()))
    }
}

impl Locked {
    /// Positive ordered observations alone change lifecycle. Absence never heals.
    pub fn observe(&mut self, observation: &Observation, now: u64) -> Result<usize, Error> {
        let fact = &observation.fact;
        document(Record::SourceFact(fact.clone()))
            .check()
            .map_err(|_| Error::Unavailable)?;
        if !policy::fresh(fact, now) {
            return Err(Error::Unavailable);
        }
        let key = grouping::key(fact);
        if let Some(index) = self.state.groups.iter().position(|g| g.key == key) {
            let group = &mut self.state.groups[index];
            let old_time = group.snapshot_at;
            let new_time = policy::source_time(fact).ok_or(Error::Unavailable)?;
            if new_time < old_time {
                return Ok(index);
            }
            group.snapshot_at = new_time;
            if !same_binding(&group.observation, observation) {
                group.invalidated = true;
            }
            // Never rewrite the original exact binding of an existing attempt.
            // A changed comment/content is ambiguity/currentness failure, not a new group.
            if policy::closed(fact) {
                group.closed = true;
                if let Some(d) = &mut group.dispatch {
                    d.group_state = GroupState::Closed;
                }
            } else if !group.closed && !group.invalidated {
                if new_time == old_time && group.observation != *observation {
                    group.invalidated = true;
                    return Ok(index);
                }
                group.observation = observation.clone();
            }
            return Ok(index);
        }
        let index = self.state.groups.len();
        self.state.groups.push(Group {
            key,
            observation: observation.clone(),
            closed: policy::closed(fact),
            invalidated: false,
            snapshot_at: policy::source_time(fact).ok_or(Error::Unavailable)?,
            dispatch: None,
        });
        Ok(index)
    }
    pub fn recover(&mut self) -> Result<(), Error> {
        let mut changed = false;
        for group in &mut self.state.groups {
            if let Some(d) = &mut group.dispatch
                && d.state == DispatchState::Submitting
            {
                *d = recovered(d.clone());
                changed = true;
            }
        }
        if changed {
            self.save()?;
        }
        Ok(())
    }
    pub fn reserve(&mut self, index: usize, now: u64) -> Result<Option<Dispatch>, Error> {
        let group = self.state.groups.get(index).ok_or(Error::Unavailable)?;
        if group.closed || group.invalidated || group.dispatch.is_some() {
            return Ok(None);
        }
        let dispatch = Dispatch {
            submission: Submission {
                dispatch_id: OperationId::new(storage::random_hex::<16>()?).unwrap(),
                group: policy::reference(&group.observation.fact),
                preference_generation: self.state.preferences.generation,
                subscription_generation: self.state.subscription.generation,
                payload: ExternalPayload {
                    title: PayloadTitle::Attention,
                    target_token: Fingerprint::new(storage::random_hex::<32>()?).unwrap(),
                },
            },
            state: DispatchState::Reserved,
            group_state: GroupState::Open,
            reserved_at: now,
            updated_at: now,
            outcome: None,
        };
        self.state.groups[index].dispatch = Some(dispatch.clone());
        self.save()?;
        Ok(Some(dispatch))
    }
    pub fn transition(
        &mut self,
        index: usize,
        next: DispatchState,
        outcome: Option<DeliveryOutcome>,
        cause: TransitionCause,
        now: u64,
    ) -> Result<(), Error> {
        let dispatch = self
            .state
            .groups
            .get_mut(index)
            .and_then(|g| g.dispatch.as_mut())
            .ok_or(Error::Unavailable)?;
        if !dispatch.state.permits(next, cause) {
            return Err(Error::Unavailable);
        }
        dispatch.state = next;
        dispatch.outcome = outcome;
        dispatch.updated_at = dispatch.updated_at.max(now);
        self.save()
    }
}

/// Exact immutable binding comparison, excluding fresh source observation times.
pub fn same_binding(a: &Observation, b: &Observation) -> bool {
    a.content_binding == b.content_binding
        && policy::reference(&a.fact) == policy::reference(&b.fact)
        && grouping::key(&a.fact) == grouping::key(&b.fact)
        && match (&a.fact, &b.fact) {
            (SourceFact::Decision(a), SourceFact::Decision(b)) => a.risk == b.risk,
            (SourceFact::Incident(_), SourceFact::Incident(_))
            | (SourceFact::Event(_), SourceFact::Event(_)) => true,
            _ => false,
        }
}
