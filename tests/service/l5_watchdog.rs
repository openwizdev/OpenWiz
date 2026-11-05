//! LP4, synthetic planner observations only. No live runtime or delivery claim.
use openwiz_core::messaging::OpId;
use openwiz_service::health::loops::{
    Checking,
    Evidence::{Known, Unknown},
    Fault, Observation, Problem, plan,
};
use std::num::NonZeroU64;

fn id(value: &str) -> OpId {
    OpId::parse(value).unwrap()
}
fn healthy() -> Observation {
    Observation {
        loop_id: id("loop-synthetic"),
        next_due_at_ms: Known(None),
        checking: Known(vec![]),
        disabled_by_failures: Known(false),
    }
}
fn problem(fault: Fault) -> Problem {
    Problem {
        loop_id: id("loop-synthetic"),
        fault,
    }
}
fn check() -> Checking {
    Checking {
        run_id: id("run-synthetic"),
        started_at_ms: 100,
        timeout_ms: NonZeroU64::new(50).unwrap(),
    }
}
fn stuck() -> Problem {
    problem(Fault::Stuck {
        run_id: id("run-synthetic"),
        started_at_ms: 100,
        timeout_ms: NonZeroU64::new(50).unwrap(),
    })
}

// Bug: no independent loop watchdog exists; T3/T5 cover CloudRoom loops,
// while L2 covers admission, not missed/stuck/failure-disabled health items.
#[test]
fn lp4_problem_table() {
    let mut missed = healthy();
    missed.next_due_at_ms = Known(Some(100));
    let mut checking = healthy();
    checking.checking = Known(vec![check()]);
    let mut disabled = healthy();
    disabled.disabled_by_failures = Known(true);
    let mut unverified_off_reason = healthy();
    unverified_off_reason.disabled_by_failures = Unknown;
    for (name, seen, expected) in [
        ("healthy or deliberately off", healthy(), vec![]),
        (
            "missed occurrence",
            missed,
            vec![problem(Fault::Missed { due_at_ms: 100 })],
        ),
        ("check past its limit", checking, vec![stuck()]),
        (
            "explicit failure disable",
            disabled,
            vec![problem(Fault::DisabledByFailures)],
        ),
    ] {
        let output = plan(Known(&[seen]), &[], 151).unwrap();
        assert_eq!(output.open, expected, "{name}");
        assert_eq!(output.needs_you, expected, "{name}");
        assert!(output.unknown.is_empty(), "{name}");
    }
    let output = plan(Known(&[unverified_off_reason]), &[], 151).unwrap();
    assert!(output.needs_you.is_empty());
    assert!(output.open.is_empty());
    assert_eq!(output.unknown.len(), 1);
}

// Bug: detection alone emits a second item on every pass. Prior output must
// suppress the same problem, clear positive recovery, and expose changed ones.
#[test]
fn lp4_repeat_fix_and_problem_change() {
    let mut broken = healthy();
    broken.next_due_at_ms = Known(Some(100));
    broken.checking = Known(vec![check()]);
    broken.disabled_by_failures = Known(true);
    let all = vec![
        problem(Fault::Missed { due_at_ms: 100 }),
        stuck(),
        problem(Fault::DisabledByFailures),
    ];
    let first = plan(Known(&[broken.clone()]), &[], 151).unwrap();
    assert_eq!(first.open, all);
    assert_eq!(first.needs_you, all);
    let repeat = plan(Known(&[broken.clone()]), &first.open, 900).unwrap();
    assert_eq!(repeat.open, all);
    assert_eq!(repeat.needs_you, vec![]);

    let fixed = plan(Known(&[healthy()]), &repeat.open, 900).unwrap();
    assert_eq!(fixed.open, vec![]);
    assert_eq!(fixed.needs_you, vec![]);
    let recur = plan(Known(&[broken]), &fixed.open, 901).unwrap();
    assert_eq!(recur.needs_you, all);

    let mut changed = healthy();
    changed.next_due_at_ms = Known(Some(800));
    changed.checking = Known(vec![Checking {
        run_id: id("run-synthetic-next"),
        started_at_ms: 800,
        timeout_ms: NonZeroU64::new(50).unwrap(),
    }]);
    let expected = vec![
        problem(Fault::Missed { due_at_ms: 800 }),
        problem(Fault::Stuck {
            run_id: id("run-synthetic-next"),
            started_at_ms: 800,
            timeout_ms: NonZeroU64::new(50).unwrap(),
        }),
    ];
    let output = plan(Known(&[changed]), &recur.open, 901).unwrap();
    assert_eq!(output.open, expected);
    assert_eq!(output.needs_you, expected);
}

// The clock and limits are literals; no elapsed-time race. A due-now check or
// a check exactly at its limit is not yet past it, and integer overflow cannot
// wrap a future deadline into an old one.
#[test]
fn lp4_time_boundaries() {
    let mut seen = healthy();
    seen.next_due_at_ms = Known(Some(150));
    seen.checking = Known(vec![check()]);
    for (now, expected) in [
        (149, vec![]),
        (150, vec![]),
        (
            151,
            vec![problem(Fault::Missed { due_at_ms: 150 }), stuck()],
        ),
    ] {
        let output = plan(Known(&[seen.clone()]), &[], now).unwrap();
        assert_eq!(output.open, expected, "at {now}");
        assert_eq!(output.needs_you, expected, "at {now}");
    }
    seen.next_due_at_ms = Known(Some(u64::MAX));
    seen.checking = Known(vec![Checking {
        run_id: id("run-synthetic"),
        started_at_ms: u64::MAX - 10,
        timeout_ms: NonZeroU64::new(50).unwrap(),
    }]);
    let output = plan(Known(&[seen]), &[], u64::MAX).unwrap();
    assert_eq!(output.open, vec![]);
    assert_eq!(output.needs_you, vec![]);
}

// Bug: treating an unread category or absent subject as healthy silently clears
// prior items, then repeats their notification when the evidence returns.
#[test]
fn lp4_unknown_preserves_prior_items_without_notifying() {
    use openwiz_service::health::loops::{Kind, Unknown as Unread};
    let before = vec![
        problem(Fault::Missed { due_at_ms: 100 }),
        stuck(),
        problem(Fault::DisabledByFailures),
    ];
    let mut missing_due = healthy();
    missing_due.next_due_at_ms = Unknown;
    let mut missing_checks = healthy();
    missing_checks.checking = Unknown;
    let mut missing_cause = healthy();
    missing_cause.disabled_by_failures = Unknown;
    let missing_all = Observation {
        loop_id: id("loop-synthetic"),
        next_due_at_ms: Unknown,
        checking: Unknown,
        disabled_by_failures: Unknown,
    };
    let all_unknown = vec![
        Unread {
            loop_id: id("loop-synthetic"),
            kind: Kind::Missed,
        },
        Unread {
            loop_id: id("loop-synthetic"),
            kind: Kind::Stuck,
        },
        Unread {
            loop_id: id("loop-synthetic"),
            kind: Kind::DisabledByFailures,
        },
    ];
    for (seen, expected, unknown) in [
        (
            vec![missing_due],
            vec![before[0].clone()],
            vec![all_unknown[0].clone()],
        ),
        (
            vec![missing_checks],
            vec![before[1].clone()],
            vec![all_unknown[1].clone()],
        ),
        (
            vec![missing_cause],
            vec![before[2].clone()],
            vec![all_unknown[2].clone()],
        ),
        (
            vec![missing_all.clone()],
            before.clone(),
            all_unknown.clone(),
        ),
        (vec![], before.clone(), all_unknown.clone()),
    ] {
        let output = plan(Known(&seen), &before, 200).unwrap();
        assert_eq!(output.open, expected);
        assert_eq!(output.needs_you, vec![]);
        assert_eq!(output.unknown, unknown);
    }
    let fresh_unknown = plan(Known(&[missing_all]), &[], 200).unwrap();
    assert_eq!(fresh_unknown.open, vec![]);
    assert_eq!(fresh_unknown.needs_you, vec![]);
    assert_eq!(fresh_unknown.unknown, all_unknown);
    let retained = plan(Known(&[]), &before, 200).unwrap();
    let mut broken = healthy();
    broken.next_due_at_ms = Known(Some(100));
    broken.checking = Known(vec![check()]);
    broken.disabled_by_failures = Known(true);
    assert_eq!(
        plan(Known(&[broken]), &retained.open, 201)
            .unwrap()
            .needs_you,
        vec![]
    );
}

// Bug: contradictory duplicate observations could both raise and clear a
// problem. A future admission time is also invalid evidence, not healthy.
#[test]
fn lp4_ambiguous_observations_are_refused() {
    use openwiz_service::health::loops::PlanError;
    let mut broken = healthy();
    broken.next_due_at_ms = Known(Some(100));
    let mut duplicate_runs = healthy();
    duplicate_runs.checking = Known(vec![check(), check()]);
    let mut future = healthy();
    future.checking = Known(vec![Checking {
        started_at_ms: 152,
        ..check()
    }]);
    let mut other_loop = healthy();
    other_loop.loop_id = id("loop-synthetic-other");
    other_loop.checking = Known(vec![check()]);
    let mut first_loop = healthy();
    first_loop.checking = Known(vec![check()]);
    for invalid in [
        vec![broken, healthy()],
        vec![duplicate_runs],
        vec![future],
        vec![first_loop, other_loop],
    ] {
        assert_eq!(
            plan(Known(&invalid), &[], 151),
            Err(PlanError::InvalidObservation)
        );
    }
}

// Distinct simultaneous problems must neither overwrite each other nor emit
// twice. Reversing observation order must not change the returned item order.
#[test]
fn lp4_distinct_problems_across_loops() {
    let mut first = healthy();
    first.next_due_at_ms = Known(Some(100));
    first.checking = Known(vec![
        check(),
        Checking {
            run_id: id("run-synthetic-second"),
            started_at_ms: 90,
            timeout_ms: NonZeroU64::new(60).unwrap(),
        },
    ]);
    let mut second = healthy();
    second.loop_id = id("loop-synthetic-other");
    second.disabled_by_failures = Known(true);
    let expected = vec![
        problem(Fault::Missed { due_at_ms: 100 }),
        stuck(),
        problem(Fault::Stuck {
            run_id: id("run-synthetic-second"),
            started_at_ms: 90,
            timeout_ms: NonZeroU64::new(60).unwrap(),
        }),
        Problem {
            loop_id: id("loop-synthetic-other"),
            fault: Fault::DisabledByFailures,
        },
    ];
    for observations in [vec![first.clone(), second.clone()], vec![second, first]] {
        let output = plan(Known(&observations), &[], 151).unwrap();
        assert_eq!(output.open, expected);
        assert_eq!(output.needs_you, expected);
        assert_eq!(output.unknown, vec![]);
        let repeat = plan(Known(&observations), &output.open, 152).unwrap();
        assert_eq!(repeat.open, expected);
        assert_eq!(repeat.needs_you, vec![]);
    }
}

// Bug: an unread whole observation list with no previous problems must not
// produce the same confident empty result as a verified empty observation.
#[test]
fn lp4_unread_snapshot_is_not_a_verified_empty_list() {
    let unread = plan(Unknown, &[], 200).unwrap();
    assert!(unread.snapshot_unknown);
    assert_eq!(unread.open, vec![]);
    assert_eq!(unread.needs_you, vec![]);
    let empty = plan(Known(&[]), &[], 200).unwrap();
    assert!(!empty.snapshot_unknown);
    let before = vec![stuck()];
    let retained = plan(Unknown, &before, 200).unwrap();
    assert!(retained.snapshot_unknown);
    assert_eq!(retained.open, before);
    assert_eq!(retained.needs_you, vec![]);
    assert_eq!(retained.unknown.len(), 1);
}
