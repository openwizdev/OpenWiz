//! Eligibility over independently verified source facts; no I/O or work authority.
use super::model::*;

pub fn category(fact: &SourceFact) -> Category {
    match fact {
        SourceFact::Decision(_) => Category::Decision,
        SourceFact::Incident(_) => Category::RecoveryEscalation,
        SourceFact::Event(e) => match e.category {
            OptionalCategory::CiFailed => Category::CiFailed,
            OptionalCategory::ReviewFindings => Category::ReviewFindings,
            OptionalCategory::ReCheck => Category::ReCheck,
            OptionalCategory::Merge => Category::Merge,
            OptionalCategory::AgentComplete => Category::AgentComplete,
            OptionalCategory::ReadyStockChanged => Category::ReadyStockChanged,
            OptionalCategory::LoopMissed => Category::LoopMissed,
            OptionalCategory::LoopStuck => Category::LoopStuck,
            OptionalCategory::LoopDisabled => Category::LoopDisabled,
            OptionalCategory::LoopRunChanged => Category::LoopRunChanged,
            OptionalCategory::RecoveryChanged => Category::RecoveryChanged,
            OptionalCategory::ServiceUpdate => Category::ServiceUpdate,
            OptionalCategory::ContractChanged => Category::ContractChanged,
            OptionalCategory::FleetWaitChanged => Category::FleetWaitChanged,
        },
    }
}

pub fn reference(fact: &SourceFact) -> Reference {
    match fact {
        SourceFact::Decision(f) => Reference::Decision(f.binding.clone()),
        SourceFact::Incident(f) => Reference::Incident(f.binding.clone()),
        SourceFact::Event(f) => Reference::Event(f.binding.clone()),
    }
}

/// Source verification is the reader's obligation; current=true alone is no proof.
pub fn eligible(fact: &SourceFact, preferences: &Preferences, now: u64) -> bool {
    if !preferences.enabled || !preferences.categories.enabled(category(fact)) {
        return false;
    }
    let valid = Document {
        schema: SchemaId::V1,
        record: Record::SourceFact(fact.clone()),
    }
    .check()
    .is_ok();
    if !valid || !fresh(fact, now) {
        return false;
    }
    match fact {
        SourceFact::Decision(d) => {
            d.state == RequestState::Open
                && d.current == Fact::Known(true)
                && d.risk != Risk::Unknown
        }
        SourceFact::Incident(i) => {
            i.state == IncidentState::Escalated && i.owner_escalated == Fact::Known(true)
        }
        SourceFact::Event(e) => {
            e.current == Fact::Known(true) && event_owner_matches(e.category, e.binding.source)
        }
    }
}

pub fn event_owner_matches(category: OptionalCategory, source: SourceOwner) -> bool {
    matches!(
        (category, source),
        (
            OptionalCategory::CiFailed
                | OptionalCategory::ReviewFindings
                | OptionalCategory::ReCheck,
            SourceOwner::EventRouter
        ) | (
            OptionalCategory::Merge
                | OptionalCategory::ContractChanged
                | OptionalCategory::FleetWaitChanged,
            SourceOwner::Fleet
        ) | (
            OptionalCategory::AgentComplete,
            SourceOwner::Fleet | SourceOwner::Loops
        ) | (OptionalCategory::ReadyStockChanged, SourceOwner::Plan)
            | (
                OptionalCategory::LoopMissed
                    | OptionalCategory::LoopStuck
                    | OptionalCategory::LoopDisabled,
                SourceOwner::LoopWatchdog
            )
            | (OptionalCategory::LoopRunChanged, SourceOwner::Loops)
            | (
                OptionalCategory::RecoveryChanged,
                SourceOwner::ServiceHealth | SourceOwner::LoopWatchdog
            )
            | (OptionalCategory::ServiceUpdate, SourceOwner::ServiceUpdate)
    )
}

pub fn source_time(fact: &SourceFact) -> Option<u64> {
    let freshness = match fact {
        SourceFact::Decision(f) => &f.freshness,
        SourceFact::Incident(f) => &f.freshness,
        SourceFact::Event(f) => &f.freshness,
    };
    match freshness.snapshot_at {
        Fact::Known(t) => Some(t),
        _ => None,
    }
}

pub fn fresh(fact: &SourceFact, now: u64) -> bool {
    let (coverage, freshness) = match fact {
        SourceFact::Decision(f) => (&f.coverage, &f.freshness),
        SourceFact::Incident(f) => (&f.coverage, &f.freshness),
        SourceFact::Event(f) => (&f.coverage, &f.freshness),
    };
    coverage.state == CoverageState::Complete
        && coverage.gaps.is_empty()
        && freshness.state == FreshnessState::Fresh
        && source_time(fact).is_some_and(|t| now.checked_sub(t).is_some_and(|age| age <= 70_000))
}

pub fn closed(fact: &SourceFact) -> bool {
    matches!(fact, SourceFact::Decision(d) if matches!(d.state, RequestState::Resolved | RequestState::Superseded))
        || matches!(fact, SourceFact::Incident(i) if i.state == IncidentState::Recovered)
        || matches!(fact, SourceFact::Event(e) if e.current == Fact::Known(false))
}
