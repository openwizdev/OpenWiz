use super::*;

#[test]
fn lp1_schedule_contracts_preserve_wakes_and_consumption() {
    let cases: [(&str, fn()); 4] = [
        (
            "lp1_disabled_holds_checks_and_shadow_still_checks",
            lp1_disabled_holds_checks_and_shadow_still_checks,
        ),
        (
            "lp1_events_need_a_delivered_identity_and_are_not_clock_wakes",
            lp1_events_need_a_delivered_identity_and_are_not_clock_wakes,
        ),
        (
            "lp1_once_occurrences_are_not_repeated_across_results_or_revisions",
            lp1_once_occurrences_are_not_repeated_across_results_or_revisions,
        ),
        (
            "lp1_schedule_boundaries_keep_original_occurrence_times",
            lp1_schedule_boundaries_keep_original_occurrence_times,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: schedules::{name}");
        proof();
    }
}

fn lp1_schedule_boundaries_keep_original_occurrence_times() {
    for (wake, now, expected) in [
        (Wake::Once { at_ms: 100 }, 99, vec![]),
        (Wake::Once { at_ms: 100 }, 100, vec![check("a", 100)]),
        (Wake::Once { at_ms: 100 }, 999, vec![check("a", 100)]),
        (Wake::Once { at_ms: 0 }, 0, vec![check("a", 0)]),
        (
            Wake::Once { at_ms: u64::MAX },
            u64::MAX,
            vec![check("a", u64::MAX)],
        ),
        (
            Wake::Interval {
                every_ms: nz(50),
                anchor_ms: 100,
            },
            99,
            vec![],
        ),
        (
            Wake::Interval {
                every_ms: nz(50),
                anchor_ms: 100,
            },
            100,
            vec![check("a", 100)],
        ),
        (
            Wake::Interval {
                every_ms: nz(u64::MAX),
                anchor_ms: u64::MAX,
            },
            u64::MAX,
            vec![check("a", u64::MAX)],
        ),
    ] {
        let mut s = snapshot(vec![definition("a", Priority::Normal)]);
        s.definitions[0].wake = wake;
        let p = plan(&s, now, &limits(3, 1)).unwrap();
        assert_eq!(
            p.due, expected,
            "wake={:?},now={now}",
            s.definitions[0].wake
        );
        assert_eq!(p.held, vec![]);
    }
}

fn lp1_events_need_a_delivered_identity_and_are_not_clock_wakes() {
    for event in [
        Event::PullRequestReview,
        Event::WorkflowRun,
        Event::CheckSuite,
        Event::IssueComment,
    ] {
        let mut s = snapshot(vec![definition("a", Priority::Normal)]);
        s.definitions[0].wake = Wake::Event { event };
        assert_eq!(plan(&s, u64::MAX, &limits(3, 1)).unwrap(), Plan::default());
        // Delivered events enter the same planner's check limits; saved,
        // checked deliveries subsequently use its dispatch limits.
        let delivered = [(id("a"), event, text("synthetic-event-1"))];
        assert_eq!(
            s.plan_with_events(&delivered, 200, &limits(3, 1)).unwrap(),
            Plan {
                due: vec![event_check("a", event, "synthetic-event-1")],
                held: vec![],
            }
        );
        let mut r = run("run-event", "a", Priority::Normal, RunResult::Deferred);
        r.wake = Occurrence::Event {
            event,
            event_id: text("synthetic-event-1"),
        };
        s.runs.push(r);
        assert_eq!(
            plan(&s, 200, &limits(3, 1)).unwrap().due,
            vec![Action::Dispatch {
                run_id: id("run-event")
            }]
        );
    }
}

fn lp1_once_occurrences_are_not_repeated_across_results_or_revisions() {
    for result in [
        RunResult::Checking,
        RunResult::Quiet,
        RunResult::CheckFailed,
        RunResult::CheckTimedOut,
        RunResult::Shadow,
        RunResult::Dispatching {
            dispatch_at_ms: 100,
        },
        RunResult::Created {
            dispatch_at_ms: 100,
        },
        RunResult::NotCreated {
            dispatch_at_ms: 100,
        },
        RunResult::Refused,
        RunResult::Uncertain {
            dispatch_at_ms: 100,
        },
    ] {
        let mut s = snapshot(vec![definition("a", Priority::Normal)]);
        s.runs.push(run("run-a", "a", Priority::Normal, result));
        assert_eq!(
            plan(&s, 200, &limits(3, 1)).unwrap(),
            Plan::default(),
            "{result:?}"
        );
        s.definitions[0].revision = text("synthetic-revision-2");
        assert_eq!(
            plan(&s, 200, &limits(3, 1)).unwrap(),
            Plan::default(),
            "revision change does not replay {result:?}"
        );
    }
}

fn lp1_disabled_holds_checks_and_shadow_still_checks() {
    let mut s = snapshot(vec![definition("a", Priority::Normal)]);
    s.definitions[0].enabled = false;
    assert_eq!(
        plan(&s, 200, &limits(3, 1)).unwrap(),
        Plan {
            due: vec![],
            held: vec![Held {
                action: check("a", 100),
                reason: HoldReason::Disabled
            }]
        }
    );
    s.definitions[0].enabled = true;
    s.definitions[0].mode = Mode::Shadow;
    assert_eq!(
        plan(&s, 200, &limits(3, 1)).unwrap(),
        Plan {
            due: vec![check("a", 100)],
            held: vec![]
        }
    );
}

fn event_check(name: &str, event: Event, event_id: &str) -> Action {
    Action::Check {
        loop_id: id(name),
        revision: text("synthetic-revision-1"),
        occurrence: Occurrence::Event {
            event,
            event_id: text(event_id),
        },
    }
}

fn event_definition(name: &str, priority: Priority) -> Definition {
    let mut d = definition(name, priority);
    d.wake = Wake::Event {
        event: Event::CheckSuite,
    };
    d
}

#[test]
fn delivered_event_contracts_preserve_admission_and_identity() {
    let cases: [(&str, fn()); 4] = [
        (
            "delivered_events_deduplicate_and_keep_stable_identity_order",
            delivered_events_deduplicate_and_keep_stable_identity_order,
        ),
        (
            "delivered_events_reject_invalid_input_before_admitting_checks",
            delivered_events_reject_invalid_input_before_admitting_checks,
        ),
        (
            "delivered_events_share_check_capacity_and_urgent_ordering_with_schedules",
            delivered_events_share_check_capacity_and_urgent_ordering_with_schedules,
        ),
        (
            "delivered_events_use_disabled_shadow_and_pending_work_gates",
            delivered_events_use_disabled_shadow_and_pending_work_gates,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: schedules::{name}");
        proof();
    }
}

fn delivered_events_share_check_capacity_and_urgent_ordering_with_schedules() {
    let mut s = snapshot(vec![
        event_definition("event", Priority::Normal),
        event_definition("urgent", Priority::Urgent),
        definition("timer", Priority::Normal),
    ]);
    s.runs.push(run(
        "in-flight",
        "removed",
        Priority::Normal,
        RunResult::Checking,
    ));
    let delivered = [
        (id("event"), Event::CheckSuite, text("synthetic-event")),
        (id("urgent"), Event::CheckSuite, text("synthetic-urgent")),
    ];
    let urgent = event_check("urgent", Event::CheckSuite, "synthetic-urgent");
    let normal = event_check("event", Event::CheckSuite, "synthetic-event");
    for (max, reserve, due, held) in [
        (
            0,
            0,
            vec![],
            vec![urgent.clone(), check("timer", 100), normal.clone()],
        ),
        (
            2,
            1,
            vec![urgent.clone()],
            vec![check("timer", 100), normal.clone()],
        ),
        (
            3,
            1,
            vec![urgent.clone(), check("timer", 100)],
            vec![normal.clone()],
        ),
        (
            4,
            2,
            vec![urgent.clone(), check("timer", 100)],
            vec![normal.clone()],
        ),
        (4, 0, vec![urgent, check("timer", 100), normal], vec![]),
    ] {
        let p = s
            .plan_with_events(&delivered, 200, &limits(max, reserve))
            .unwrap();
        assert_eq!(p.due, due, "max={max}, reserve={reserve}");
        assert_eq!(
            p.held,
            held.into_iter()
                .map(|action| Held {
                    action,
                    reason: HoldReason::CheckCapacity,
                })
                .collect::<Vec<_>>()
        );
    }
}

fn delivered_events_deduplicate_and_keep_stable_identity_order() {
    let mut s = snapshot(vec![
        event_definition("a", Priority::Normal),
        event_definition("b", Priority::Normal),
    ]);
    let mut delivered = vec![
        (id("a"), Event::CheckSuite, text("event-z")),
        (id("b"), Event::CheckSuite, text("event-a")),
        (id("a"), Event::CheckSuite, text("event-a")),
        (id("a"), Event::CheckSuite, text("event-a")),
    ];
    let expected = Plan {
        due: vec![event_check("a", Event::CheckSuite, "event-a")],
        held: vec!["a", "b"]
            .into_iter()
            .zip(["event-z", "event-a"])
            .map(|(name, event_id)| Held {
                action: event_check(name, Event::CheckSuite, event_id),
                reason: HoldReason::CheckCapacity,
            })
            .collect(),
    };
    assert_eq!(
        s.plan_with_events(&delivered, 200, &limits(1, 0)).unwrap(),
        expected
    );
    delivered.reverse();
    s.definitions.reverse();
    assert_eq!(
        s.plan_with_events(&delivered, 200, &limits(1, 0)).unwrap(),
        expected
    );
    // Holding a delivery without saving a run must not consume it.
    assert_eq!(
        s.plan_with_events(&delivered, 200, &limits(4, 0))
            .unwrap()
            .due,
        vec![
            event_check("a", Event::CheckSuite, "event-a"),
            event_check("a", Event::CheckSuite, "event-z"),
            event_check("b", Event::CheckSuite, "event-a")
        ]
    );
    for result in [
        RunResult::Checking,
        RunResult::Quiet,
        RunResult::CheckFailed,
        RunResult::CheckTimedOut,
        RunResult::Shadow,
        RunResult::Deferred,
        RunResult::Dispatching {
            dispatch_at_ms: 100,
        },
        RunResult::Created {
            dispatch_at_ms: 100,
        },
        RunResult::NotCreated {
            dispatch_at_ms: 100,
        },
        RunResult::Refused,
        RunResult::Uncertain {
            dispatch_at_ms: 100,
        },
    ] {
        let mut s = snapshot(vec![event_definition("a", Priority::Normal)]);
        let mut r = run("saved-event", "a", Priority::Normal, result);
        r.wake = Occurrence::Event {
            event: Event::CheckSuite,
            event_id: text("event-a"),
        };
        s.runs.push(r);
        for revision in ["synthetic-revision-1", "synthetic-revision-2"] {
            s.definitions[0].revision = text(revision);
            assert_eq!(
                s.plan_with_events(
                    &[(id("a"), Event::CheckSuite, text("event-a"))],
                    200,
                    &limits(3, 1)
                )
                .unwrap(),
                plan(&s, 200, &limits(3, 1)).unwrap(),
                "{result:?}, {revision}"
            );
        }
    }
}

fn delivered_events_use_disabled_shadow_and_pending_work_gates() {
    let mut s = snapshot(vec![event_definition("a", Priority::Normal)]);
    let delivered = [(id("a"), Event::CheckSuite, text("event-new"))];
    let action = event_check("a", Event::CheckSuite, "event-new");
    s.definitions[0].enabled = false;
    assert_eq!(
        s.plan_with_events(&delivered, 200, &limits(3, 1)).unwrap(),
        Plan {
            due: vec![],
            held: vec![Held {
                action: action.clone(),
                reason: HoldReason::Disabled
            }],
        }
    );
    s.definitions[0].enabled = true;
    s.definitions[0].mode = Mode::Shadow;
    assert_eq!(
        s.plan_with_events(&delivered, 200, &limits(3, 1)).unwrap(),
        Plan {
            due: vec![action.clone()],
            held: vec![]
        }
    );
    s.definitions[0].mode = Mode::Active;
    let mut r = run("pending", "a", Priority::Normal, RunResult::Deferred);
    r.wake = Occurrence::Event {
        event: Event::CheckSuite,
        event_id: text("event-old"),
    };
    s.runs.push(r);
    assert_eq!(
        s.plan_with_events(&delivered, 200, &limits(3, 1)).unwrap(),
        Plan {
            due: vec![Action::Dispatch {
                run_id: id("pending")
            }],
            held: vec![Held {
                action,
                reason: HoldReason::WorkPending
            }],
        }
    );
}

fn delivered_events_reject_invalid_input_before_admitting_checks() {
    let s = snapshot(vec![
        event_definition("a", Priority::Normal),
        definition("timer", Priority::Normal),
    ]);
    for bad in [
        (id("missing"), Event::CheckSuite, text("event")),
        (id("timer"), Event::CheckSuite, text("event")),
        (id("a"), Event::WorkflowRun, text("event")),
        (id("a"), Event::CheckSuite, text(" \t")),
        (id("a"), Event::CheckSuite, text("bad\0event")),
    ] {
        assert_eq!(
            s.plan_with_events(
                &[(id("a"), Event::CheckSuite, text("valid-event")), bad],
                200,
                &limits(3, 1)
            ),
            Err(PlanError::InvalidSnapshot)
        );
    }
}
