use super::*;

fn interval() -> Snapshot {
    let mut s = snapshot(vec![definition("a", Priority::Normal)]);
    s.definitions[0].wake = Wake::Interval {
        every_ms: nz(50),
        anchor_ms: 100,
    };
    s
}
fn admitted(due: u64, started: u64, updated: u64) -> Run {
    let mut r = run(
        &format!("run-{due}"),
        "a",
        Priority::Normal,
        RunResult::Quiet,
    );
    r.wake = Occurrence::Scheduled { due_at_ms: due };
    r.started_at_ms = started;
    r.updated_at_ms = updated;
    r
}

#[test]
fn lp1_missed_contracts_preserve_occurrence_identity() {
    let cases: [(&str, fn()); 6] = [
        (
            "lp1_an_old_event_record_does_not_consume_a_scheduled_occurrence",
            lp1_an_old_event_record_does_not_consume_a_scheduled_occurrence,
        ),
        (
            "lp1_coalescing_survives_restart_revision_and_every_recorded_result",
            lp1_coalescing_survives_restart_revision_and_every_recorded_result,
        ),
        (
            "lp1_held_checks_do_not_consume_missed_occurrences",
            lp1_held_checks_do_not_consume_missed_occurrences,
        ),
        (
            "lp1_interval_coalescing_never_wraps_or_walks_the_missed_tick_count",
            lp1_interval_coalescing_never_wraps_or_walks_the_missed_tick_count,
        ),
        (
            "lp1_missed_intervals_keep_oldest_due_and_coalesce_through_admission",
            lp1_missed_intervals_keep_oldest_due_and_coalesce_through_admission,
        ),
        (
            "lp1_urgent_first_then_oldest_due_then_loop_id",
            lp1_urgent_first_then_oldest_due_then_loop_id,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: missed::{name}");
        proof();
    }
}

fn lp1_missed_intervals_keep_oldest_due_and_coalesce_through_admission() {
    for (now, records, expected) in [
        (99, vec![], vec![]),
        (100, vec![], vec![check("a", 100)]),
        (149, vec![], vec![check("a", 100)]),
        (375, vec![], vec![check("a", 100)]),
        (149, vec![(100, 100, 100)], vec![]),
        (150, vec![(100, 100, 100)], vec![check("a", 150)]),
        (375, vec![(100, 100, 100)], vec![check("a", 150)]),
        (375, vec![(100, 375, 375)], vec![]),
        (399, vec![(100, 375, 399)], vec![]),
        (400, vec![(100, 375, 399)], vec![check("a", 400)]),
        (449, vec![(100, 375, 399), (400, 425, 425)], vec![]),
        (
            450,
            vec![(400, 425, 425), (100, 375, 399)],
            vec![check("a", 450)],
        ),
        // A later update is never a new admission/coalescing watermark.
        (1000, vec![(100, 100, 1000)], vec![check("a", 150)]),
        // A later covered interval must not erase an earlier missing one.
        (375, vec![(200, 300, 300)], vec![check("a", 100)]),
        (
            375,
            vec![(100, 100, 100), (200, 300, 300)],
            vec![check("a", 150)],
        ),
        (
            375,
            vec![(200, 300, 300), (100, 175, 175)],
            vec![check("a", 350)],
        ),
    ] {
        let mut s = interval();
        s.runs = records
            .into_iter()
            .map(|(d, a, u)| admitted(d, a, u))
            .collect();
        let p = plan(&s, now, &limits(10, 0)).unwrap();
        assert_eq!(p.due, expected, "now={now},records={:?}", s.runs);
        assert_eq!(p.held, vec![]);
        s.runs.reverse();
        assert_eq!(p, plan(&s, now, &limits(10, 0)).unwrap());
    }
}

fn lp1_coalescing_survives_restart_revision_and_every_recorded_result() {
    for result in [
        RunResult::Checking,
        RunResult::Quiet,
        RunResult::CheckFailed,
        RunResult::CheckTimedOut,
        RunResult::Shadow,
        RunResult::Deferred,
        RunResult::Dispatching {
            dispatch_at_ms: 375,
        },
        RunResult::Created {
            dispatch_at_ms: 375,
        },
        RunResult::NotCreated {
            dispatch_at_ms: 375,
        },
        RunResult::Refused,
        RunResult::Uncertain {
            dispatch_at_ms: 375,
        },
    ] {
        let mut s = interval();
        let mut r = admitted(100, 375, 399);
        r.result = result;
        s.runs.push(r);
        let p = plan(&s, 399, &limits(10, 0)).unwrap();
        let expected = if result == RunResult::Deferred {
            vec![Action::Dispatch {
                run_id: id("run-100"),
            }]
        } else {
            vec![]
        };
        assert_eq!(p.due, expected, "{result:?}");
        assert_eq!(p.held, vec![]);
        assert_eq!(
            p,
            plan(&s.clone(), 399, &limits(10, 0)).unwrap(),
            "restart on saved records"
        );
        s.definitions[0].revision = text("synthetic-revision-2");
        let p = plan(&s, 399, &limits(10, 0)).unwrap();
        assert_eq!(
            p.due,
            vec![],
            "revision change does not replay coalesced checks"
        );
        assert_eq!(
            p.held,
            if result == RunResult::Deferred {
                vec![Held {
                    action: Action::Dispatch {
                        run_id: id("run-100"),
                    },
                    reason: HoldReason::RevisionChanged,
                }]
            } else {
                vec![]
            }
        );
    }
}

fn lp1_held_checks_do_not_consume_missed_occurrences() {
    let mut s = interval();
    for now in [375, 399, 400] {
        assert_eq!(
            plan(&s, now, &limits(0, 0)).unwrap(),
            Plan {
                due: vec![],
                held: vec![Held {
                    action: check("a", 100),
                    reason: HoldReason::CheckCapacity
                }]
            }
        );
        s.definitions[0].enabled = false;
        assert_eq!(
            plan(&s, now, &limits(10, 0)).unwrap(),
            Plan {
                due: vec![],
                held: vec![Held {
                    action: check("a", 100),
                    reason: HoldReason::Disabled
                }]
            }
        );
        s.definitions[0].enabled = true;
    }
    assert_eq!(
        plan(&s, 400, &limits(10, 0)).unwrap().due,
        vec![check("a", 100)]
    );
    s.runs.push(admitted(100, 400, 400));
    assert_eq!(plan(&s, 449, &limits(10, 0)).unwrap(), Plan::default());
    assert_eq!(
        plan(&s, 450, &limits(10, 0)).unwrap().due,
        vec![check("a", 450)]
    );
}

fn lp1_urgent_first_then_oldest_due_then_loop_id() {
    let mut s = snapshot(vec![
        definition("a", Priority::Normal),
        definition("b", Priority::Normal),
        definition("c", Priority::Normal),
        definition("u", Priority::Urgent),
    ]);
    for (d, anchor) in s.definitions.iter_mut().zip([100, 50, 50, 125]) {
        d.wake = Wake::Interval {
            every_ms: nz(50),
            anchor_ms: anchor,
        };
    }
    let p = plan(&s, 400, &limits(3, 1)).unwrap();
    assert_eq!(p.due, vec![check("u", 125), check("b", 50), check("c", 50)]);
    assert_eq!(
        p.held,
        vec![Held {
            action: check("a", 100),
            reason: HoldReason::CheckCapacity
        }]
    );
}

fn lp1_interval_coalescing_never_wraps_or_walks_the_missed_tick_count() {
    for (anchor, every, records, expected) in [
        (0, 1, vec![], vec![check("a", 0)]),
        (0, 1, vec![(0, u64::MAX, u64::MAX)], vec![]),
        (u64::MAX, 1, vec![], vec![check("a", u64::MAX)]),
        (u64::MAX, 1, vec![(u64::MAX, u64::MAX, u64::MAX)], vec![]),
        (0, u64::MAX, vec![(0, 0, 0)], vec![check("a", u64::MAX)]),
        (100, u64::MAX, vec![(100, u64::MAX, u64::MAX)], vec![]),
    ] {
        let mut s = interval();
        s.definitions[0].wake = Wake::Interval {
            every_ms: nz(every),
            anchor_ms: anchor,
        };
        s.runs = records
            .into_iter()
            .map(|(d, a, u)| admitted(d, a, u))
            .collect();
        assert_eq!(
            plan(&s, u64::MAX, &limits(10, 0)).unwrap(),
            Plan {
                due: expected,
                held: vec![]
            }
        );
    }
}

fn lp1_an_old_event_record_does_not_consume_a_scheduled_occurrence() {
    let mut s = interval();
    let mut r = admitted(100, 375, 375);
    r.definition_revision = text("synthetic-old-event-revision");
    r.wake = Occurrence::Event {
        event: Event::CheckSuite,
        event_id: text("synthetic-event"),
    };
    s.runs.push(r);
    assert_eq!(
        plan(&s, 375, &limits(10, 0)).unwrap().due,
        vec![check("a", 100)]
    );
}
