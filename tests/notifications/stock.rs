//! PA6: source-fact classification, which T1's shape/arithmetic checks do not exercise.
use openwiz_core::notifications::{model::*, stock::*};
fn ticket(n: u64) -> TicketFacts {
    TicketFacts {
        number: n,
        open: Fact::Known(true),
        merged: Fact::Known(false),
        labels: Fact::Known(vec!["ready-for-agent".into()]),
        start_recorded: Fact::Known(false),
        matching_open_pr: Fact::Known(false),
        blockers_merged: Fact::Known(true),
        capacity_refused: None,
    }
}
fn input(tickets: Vec<TicketFacts>) -> ProjectFacts {
    ProjectFacts {
        project: Id::new("synthetic-alder").unwrap(),
        coverage: Coverage {
            state: CoverageState::Complete,
            gaps: vec![],
        },
        snapshot_at: Fact::Known(100_000),
        tickets: Fact::Known(tickets),
        last_good: None,
    }
}
fn counts(p: &ProjectStock) -> &StockCounts {
    let Fact::Known(c) = &p.counts else {
        panic!("counts must be known: {p:?}")
    };
    c
}
#[test]
fn stock_partition_and_state_matrix() {
    for (ready, running, state) in [
        (4, 2, StockState::Fed),
        (3, 2, StockState::LowStock),
        (0, 2, StockState::RunningDry),
        (3, 0, StockState::NoBuilders),
        (0, 0, StockState::RunningDry),
    ] {
        let mut rows = vec![];
        for i in 0..ready {
            rows.push(ticket(i + 1));
        }
        for i in 0..running {
            let mut t = ticket(i + 100);
            t.start_recorded = Fact::Known(true);
            t.blockers_merged = Fact::Known(false);
            t.labels = Fact::Known(vec!["held".into()]);
            rows.push(t);
        }
        for (i, label) in [
            (200, "held"),
            (201, "needs-info"),
            (202, "ready-for-human"),
            (203, "unapproved"),
        ] {
            let mut t = ticket(i);
            t.labels = Fact::Known(vec![label.into()]);
            t.blockers_merged = Fact::Known(false);
            rows.push(t);
        }
        let mut blocked = ticket(204);
        blocked.blockers_merged = Fact::Known(false);
        rows.push(blocked);
        let mut capacity = ticket(205);
        capacity.capacity_refused = Some(Fact::Known(true));
        rows.push(capacity);
        let p = project(input(rows), 100_000);
        let c = counts(&p);
        assert_eq!(
            (
                c.ready,
                c.running,
                c.blocked,
                c.held,
                c.unapproved,
                c.owner_wait,
                c.capacity_wait,
                c.unknown,
                c.state
            ),
            (ready, running, 1, 1, 1, 2, 1, 0, state)
        );
    }
}
#[test]
fn stock_required_unknowns_do_not_fall_into_lower_buckets() {
    let mut rows = vec![];
    let mut t = ticket(1);
    t.start_recorded = unknown("unread start");
    t.labels = Fact::Known(vec!["held".into()]);
    rows.push(t);
    let mut t = ticket(2);
    t.matching_open_pr = unknown("unread title");
    rows.push(t);
    let mut t = ticket(3);
    t.capacity_refused = Some(unknown("unread capacity"));
    rows.push(t);
    let mut t = ticket(4);
    t.blockers_merged = unknown("unverified closed blocker");
    rows.push(t);
    let mut t = ticket(5);
    t.start_recorded = unknown("unread start");
    t.matching_open_pr = Fact::Known(true);
    rows.push(t);
    let p = project(input(rows), 100_000);
    let c = counts(&p);
    assert_eq!(
        (c.ready, c.running, c.held, c.unknown, c.state),
        (0, 1, 0, 4, StockState::Indeterminate)
    );
    assert_eq!(p.coverage.state, CoverageState::Partial);
}
#[test]
fn stock_original_time_and_last_good_are_retained() {
    let sample = StockSample {
        snapshot_at: 100_000,
        counts: StockCounts {
            ready: 3,
            running: 0,
            blocked: 0,
            held: 0,
            unapproved: 0,
            owner_wait: 0,
            capacity_wait: 0,
            unknown: 0,
            state: StockState::NoBuilders,
        },
    };
    let mut i = input(vec![ticket(1)]);
    i.last_good = Some(sample.clone());
    let p = project(i.clone(), 170_000);
    assert_eq!(p.freshness.state, FreshnessState::Fresh);
    let p = project(i.clone(), 170_001);
    assert_eq!(p.freshness.state, FreshnessState::Stale);
    assert_eq!(p.last_good, Some(sample.clone()));
    i.snapshot_at = Fact::Known(200_000);
    let p = project(i, 170_001);
    assert_eq!(p.freshness.state, FreshnessState::Unknown);
    assert_eq!(p.last_good, Some(sample));
    assert_eq!(p.coverage.state, CoverageState::Partial);
}
#[test]
fn stock_factory_requires_full_scope_and_original_ages() {
    let cov = Coverage {
        state: CoverageState::Complete,
        gaps: vec![],
    };
    let one = project(input(vec![ticket(1)]), 100_000);
    let f = factory(
        vec![one.clone()],
        cov.clone(),
        Fact::Known(100_000),
        100_000,
    );
    assert_eq!(f.check(), Ok(()));
    let Fact::Known(c) = f.totals else {
        panic!("complete totals")
    };
    assert_eq!(
        (c.ready, c.running, c.state),
        (1, 0, StockState::NoBuilders)
    );
    let mut missing = input(vec![]);
    missing.project = Id::new("synthetic-birch").unwrap();
    missing.tickets = unknown("Unread configured project");
    let f = factory(
        vec![one.clone(), project(missing, 100_000)],
        cov.clone(),
        Fact::Known(100_000),
        100_000,
    );
    assert_eq!(f.projects.len(), 2);
    assert!(matches!(f.totals, Fact::Unknown(_)));
    assert_eq!(f.check(), Ok(()));
    let f = factory(
        vec![one.clone()],
        cov.clone(),
        Fact::Known(100_000),
        170_001,
    );
    assert_eq!(f.freshness.state, FreshnessState::Stale);
    assert!(matches!(f.totals, Fact::Unknown(_)));
    let f = factory(vec![one.clone(), one], cov, Fact::Known(100_000), 100_000);
    assert_eq!(f.projects.len(), 1);
    assert!(
        matches!(f.projects[0].counts, Fact::Unknown(_)),
        "duplicate project readings cannot select one count"
    );
    assert!(matches!(f.totals, Fact::Unknown(_)));
}
#[test]
fn stock_review_future_discovery_time_cannot_be_hidden_by_older_project() {
    let p = project(input(vec![ticket(1)]), 100_000);
    let f = factory(
        vec![p],
        Coverage {
            state: CoverageState::Complete,
            gaps: vec![],
        },
        Fact::Known(200_000),
        100_000,
    );
    assert!(
        matches!(f.totals, Fact::Unknown(_)),
        "future discovery cannot publish totals"
    );
    assert_eq!(f.freshness.state, FreshnessState::Unknown);
    assert_eq!(f.coverage.state, CoverageState::Partial);
}
#[test]
fn stock_review_factory_preserves_gap_source_owners() {
    let mut i = input(vec![]);
    i.coverage = Coverage {
        state: CoverageState::Partial,
        gaps: vec![Gap {
            source: SourceOwner::Inventory,
            reason: text("Synthetic inventory source gap"),
        }],
    };
    let f = factory(
        vec![project(i, 100_000)],
        Coverage {
            state: CoverageState::Complete,
            gaps: vec![],
        },
        Fact::Known(100_000),
        100_000,
    );
    assert!(
        f.coverage
            .gaps
            .iter()
            .any(|g| g.source == SourceOwner::Inventory
                && g.reason.as_str() == "Synthetic inventory source gap")
    );
}
#[test]
fn stock_absent_capacity_source_does_not_hold_ready_work() {
    let p = project(input(vec![ticket(1)]), 100_000);
    assert_eq!(
        (
            counts(&p).ready,
            counts(&p).capacity_wait,
            counts(&p).unknown
        ),
        (1, 0, 0)
    );
}
