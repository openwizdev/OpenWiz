//! PA2/PA3: pure policy over synthetic, independently supplied source facts.
use openwiz_core::notifications::{model::*, policy};

fn decision() -> SourceFact {
    SourceFact::Decision(DecisionFact {
        binding: DecisionRef {
            repository: Repository::new("synthetic/factory").unwrap(),
            subject: Subject {
                kind: SubjectKind::Issue,
                number: 41.try_into().unwrap(),
            },
            comment_id: 51.try_into().unwrap(),
            request_id: RequestId::new("proposal-1").unwrap(),
            fingerprint: Fingerprint::new("a".repeat(64)).unwrap(),
        },
        state: RequestState::Open,
        current: Fact::Known(true),
        risk: Risk::Ordinary,
        coverage: Coverage {
            state: CoverageState::Complete,
            gaps: vec![],
        },
        freshness: Freshness {
            state: FreshnessState::Fresh,
            snapshot_at: Fact::Known(100_000),
        },
    })
}

#[test]
fn explicit_enable_currentness_risk_and_source_age_govern_decisions() {
    let source = decision();
    let mut preferences = Preferences::off();
    assert!(!policy::eligible(&source, &preferences, 100_000));
    preferences.enabled = true;
    assert!(policy::eligible(&source, &preferences, 100_000));
    assert!(policy::eligible(&source, &preferences, 170_000));
    assert!(!policy::eligible(&source, &preferences, 170_001));
    assert!(!policy::eligible(&source, &preferences, 99_999));
    for mutate in 0..6 {
        let mut bad = source.clone();
        let SourceFact::Decision(d) = &mut bad else {
            unreachable!()
        };
        match mutate {
            0 => d.state = RequestState::Resolved,
            1 => d.state = RequestState::Superseded,
            2 => d.current = Fact::Known(false),
            3 => d.current = Fact::Unknown(Text::new("Independent proposal unread").unwrap()),
            4 => d.risk = Risk::Unknown,
            _ => d.freshness.state = FreshnessState::Stale,
        }
        assert!(
            !policy::eligible(&bad, &preferences, 100_000),
            "case {mutate}"
        );
    }
    preferences.categories.decision = false;
    assert!(!policy::eligible(&source, &preferences, 100_000));
}

#[test]
fn recovery_requires_owner_escalation_and_optional_categories_need_their_own_choice() {
    let complete = Coverage {
        state: CoverageState::Complete,
        gaps: vec![],
    };
    let fresh = Freshness {
        state: FreshnessState::Fresh,
        snapshot_at: Fact::Known(100_000),
    };
    let mut preferences = Preferences::off();
    preferences.enabled = true;
    let mut incident = SourceFact::Incident(IncidentFact {
        binding: IncidentRef {
            repository: Repository::new("synthetic/factory").unwrap(),
            owner: Id::new("owner-1").unwrap(),
            source: RecoverySource::ServiceHealth,
            subject: Id::new("health-1").unwrap(),
            incident: Id::new("incident-1").unwrap(),
        },
        state: IncidentState::Repairing,
        owner_escalated: Fact::Known(true),
        coverage: complete.clone(),
        freshness: fresh.clone(),
    });
    assert!(!policy::eligible(&incident, &preferences, 100_000));
    if let SourceFact::Incident(i) = &mut incident {
        i.state = IncidentState::Escalated;
    }
    assert!(policy::eligible(&incident, &preferences, 100_000));
    if let SourceFact::Incident(i) = &mut incident {
        i.owner_escalated = Fact::Known(false);
    }
    assert!(!policy::eligible(&incident, &preferences, 100_000));
    for (category, source) in [
        (OptionalCategory::CiFailed, SourceOwner::EventRouter),
        (OptionalCategory::ReviewFindings, SourceOwner::EventRouter),
        (OptionalCategory::ReCheck, SourceOwner::EventRouter),
        (OptionalCategory::Merge, SourceOwner::Fleet),
        (OptionalCategory::AgentComplete, SourceOwner::Fleet),
        (OptionalCategory::ReadyStockChanged, SourceOwner::Plan),
        (OptionalCategory::LoopMissed, SourceOwner::LoopWatchdog),
        (OptionalCategory::LoopStuck, SourceOwner::LoopWatchdog),
        (OptionalCategory::LoopDisabled, SourceOwner::LoopWatchdog),
        (OptionalCategory::LoopRunChanged, SourceOwner::Loops),
        (
            OptionalCategory::RecoveryChanged,
            SourceOwner::ServiceHealth,
        ),
        (OptionalCategory::ServiceUpdate, SourceOwner::ServiceUpdate),
        (OptionalCategory::ContractChanged, SourceOwner::Fleet),
        (OptionalCategory::FleetWaitChanged, SourceOwner::Fleet),
    ] {
        let event = SourceFact::Event(EventFact {
            binding: EventRef {
                repository: Repository::new("synthetic/factory").unwrap(),
                source,
                subject: Id::new("subject-1").unwrap(),
                event_id: Id::new("event-1").unwrap(),
                revision: Id::new("revision-1").unwrap(),
            },
            category,
            current: Fact::Known(true),
            coverage: complete.clone(),
            freshness: fresh.clone(),
        });
        assert!(
            !policy::eligible(&event, &preferences, 100_000),
            "default category {category:?}"
        );
        let mut selected = preferences.clone();
        let mut toggles = serde_json::to_value(&selected.categories).unwrap();
        let name = serde_json::to_value(category).unwrap();
        toggles[name.as_str().unwrap()] = serde_json::json!(true);
        selected.categories = serde_json::from_value(toggles).unwrap();
        assert!(
            policy::eligible(&event, &selected, 100_000),
            "explicit category {category:?}"
        );
    }
}

#[test]
fn group_identity_excludes_poll_comment_and_includes_repository_proposal_and_owner() {
    use openwiz_core::notifications::grouping;
    let original = decision();
    let key = grouping::key(&original);
    let mut copied = original.clone();
    if let SourceFact::Decision(d) = &mut copied {
        d.binding.comment_id = 52.try_into().unwrap();
        d.freshness.snapshot_at = Fact::Known(99_999);
    }
    assert_eq!(grouping::key(&copied), key);
    for field in 0..4 {
        let mut distinct = original.clone();
        let SourceFact::Decision(d) = &mut distinct else {
            unreachable!()
        };
        match field {
            0 => d.binding.repository = Repository::new("synthetic/other").unwrap(),
            1 => d.binding.subject.kind = SubjectKind::PullRequest,
            2 => d.binding.request_id = RequestId::new("request-2").unwrap(),
            _ => d.binding.fingerprint = Fingerprint::new("c".repeat(64)).unwrap(),
        }
        assert_ne!(grouping::key(&distinct), key);
    }
}
