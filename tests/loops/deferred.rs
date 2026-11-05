use super::*;

fn interval() -> Snapshot {
    let mut s = snapshot(vec![definition("a", Priority::Normal)]);
    s.definitions[0].wake = Wake::Interval {
        every_ms: nz(50),
        anchor_ms: 100,
    };
    s
}

fn dispatch() -> Action {
    Action::Dispatch {
        run_id: id("run-100"),
    }
}

#[test]
fn lp1_deferred_contracts_preserve_pending_admission() {
    let cases: [(&str, fn()); 6] = [
        (
            "r1_deferred_ticks_save_one_run_and_dispatch_once_when_capacity_frees",
            r1_deferred_ticks_save_one_run_and_dispatch_once_when_capacity_frees,
        ),
        (
            "r1_non_deferred_records_do_not_hold_the_next_scheduled_check",
            r1_non_deferred_records_do_not_hold_the_next_scheduled_check,
        ),
        (
            "r1_pending_work_preserves_dispatch_gates_and_leaves_check_capacity_for_other_loops",
            r1_pending_work_preserves_dispatch_gates_and_leaves_check_capacity_for_other_loops,
        ),
        (
            "r3_permanent_dispatch_holds_allow_checks_even_after_many_missed_ticks",
            r3_permanent_dispatch_holds_allow_checks_even_after_many_missed_ticks,
        ),
        (
            "r3_used_positive_budget_coalesces_until_the_saved_charge_expires",
            r3_used_positive_budget_coalesces_until_the_saved_charge_expires,
        ),
        (
            "r3_zero_budget_keeps_checking_across_ticks_without_dispatching",
            r3_zero_budget_keeps_checking_across_ticks_without_dispatching,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: deferred::{name}");
        proof();
    }
}

fn r1_deferred_ticks_save_one_run_and_dispatch_once_when_capacity_frees() {
    let mut s = interval();
    let mut l = limits(10, 0);
    l.agents = Capacity {
        max: 0,
        urgent_reserve: 0,
    };
    // Save only checks the public planner admits, as the executor would.
    // The reviewer's five ticks used to accumulate five deferred runs.
    for now in [100, 150, 200, 250, 300] {
        for action in plan(&s, now, &l).unwrap().due {
            let Action::Check { occurrence, .. } = action else {
                panic!("agent capacity is zero");
            };
            let mut r = run(
                &format!("run-{now}"),
                "a",
                Priority::Normal,
                RunResult::Deferred,
            );
            r.wake = occurrence;
            r.started_at_ms = now;
            r.updated_at_ms = now;
            s.runs.push(r);
        }
    }
    assert_eq!(s.runs.len(), 1, "ticks must not accumulate found work");
    assert_eq!(s.runs[0].id, id("run-100"));
    assert_eq!(
        plan(&s, 300, &l).unwrap(),
        Plan {
            due: vec![],
            held: vec![
                Held {
                    action: dispatch(),
                    reason: HoldReason::AgentCapacity,
                },
                Held {
                    action: check("a", 150),
                    reason: HoldReason::WorkPending,
                },
            ],
        }
    );
    l.agents.max = 10;
    let p = plan(&s, 300, &l).unwrap();
    assert_eq!(p.due, vec![dispatch()]);
    assert_eq!(
        p.held,
        vec![Held {
            action: check("a", 150),
            reason: HoldReason::WorkPending,
        }]
    );
    assert_eq!(p, plan(&s.clone(), 300, &l).unwrap(), "restart");

    // Once the saved dispatch settles, admit the oldest held occurrence.
    // Its admission coalesces the rest of the withheld ticks through 300.
    s.runs[0].result = RunResult::Created {
        dispatch_at_ms: 300,
    };
    s.runs[0].updated_at_ms = 300;
    assert_eq!(plan(&s, 300, &l).unwrap().due, vec![check("a", 150)]);
    let mut next = run("run-150", "a", Priority::Normal, RunResult::Quiet);
    next.wake = Occurrence::Scheduled { due_at_ms: 150 };
    next.started_at_ms = 300;
    next.updated_at_ms = 300;
    s.runs.push(next);
    assert_eq!(plan(&s, 300, &l).unwrap(), Plan::default());
    assert_eq!(plan(&s, 349, &l).unwrap(), Plan::default());
    assert_eq!(plan(&s, 350, &l).unwrap().due, vec![check("a", 350)]);
}

fn r1_pending_work_preserves_dispatch_gates_and_leaves_check_capacity_for_other_loops() {
    for (case, dispatch_reason, pending) in [
        ("capacity", HoldReason::AgentCapacity, true),
        ("budget", HoldReason::Budget, false),
        ("unread", HoldReason::AgentOccupancyUnknown, true),
        ("revision", HoldReason::RevisionChanged, false),
        ("shadow", HoldReason::Shadow, false),
        ("off", HoldReason::Disabled, false),
    ] {
        let mut s = interval();
        s.runs
            .push(run("run-100", "a", Priority::Normal, RunResult::Deferred));
        let mut b = definition("b", Priority::Normal);
        b.wake = Wake::Once { at_ms: 200 };
        s.definitions.push(b);
        let mut l = limits(1, 0);
        match case {
            "capacity" => {
                l.agents = Capacity {
                    max: 0,
                    urgent_reserve: 0,
                }
            }
            "budget" => s.definitions[0].budget.max_agent_starts = 0,
            "unread" => s.active_agents = None,
            "revision" => s.definitions[0].revision = text("synthetic-revision-2"),
            "shadow" => s.definitions[0].mode = Mode::Shadow,
            "off" => s.definitions[0].enabled = false,
            _ => unreachable!(),
        }
        let mut next_check = check("a", 150);
        if let Action::Check { revision, .. } = &mut next_check {
            *revision = s.definitions[0].revision.clone();
        }
        let p = plan(&s, 200, &l).unwrap();
        let (due, held_check) = if pending || case == "off" {
            (
                check("b", 200),
                Held {
                    action: next_check,
                    reason: if case == "off" {
                        HoldReason::Disabled
                    } else {
                        HoldReason::WorkPending
                    },
                },
            )
        } else {
            (
                next_check,
                Held {
                    action: check("b", 200),
                    reason: HoldReason::CheckCapacity,
                },
            )
        };
        assert_eq!(p.due, vec![due], "{case}");
        assert_eq!(
            p.held,
            vec![
                Held {
                    action: dispatch(),
                    reason: dispatch_reason
                },
                held_check
            ],
            "{case}"
        );
        s.definitions.reverse();
        assert_eq!(p, plan(&s, 200, &l).unwrap(), "order: {case}");
    }
}

fn r3_permanent_dispatch_holds_allow_checks_even_after_many_missed_ticks() {
    for (case, reason) in [
        ("revision", HoldReason::RevisionChanged),
        ("budget", HoldReason::Budget),
        ("shadow", HoldReason::Shadow),
    ] {
        let mut s = interval();
        s.runs
            .push(run("run-100", "a", Priority::Normal, RunResult::Deferred));
        match case {
            "revision" => s.definitions[0].revision = text("synthetic-revision-2"),
            "budget" => s.definitions[0].budget.max_agent_starts = 0,
            "shadow" => s.definitions[0].mode = Mode::Shadow,
            _ => unreachable!(),
        }
        let saved = s.clone();
        let mut oldest = check("a", 150);
        if let Action::Check { revision, .. } = &mut oldest {
            *revision = s.definitions[0].revision.clone();
        }
        for now in [200, 1000, 100000] {
            assert_eq!(
                plan(&s, now, &limits(1, 0)).unwrap(),
                Plan {
                    due: vec![oldest.clone()],
                    held: vec![Held {
                        action: dispatch(),
                        reason
                    }],
                },
                "{case} at {now}"
            );
            assert_eq!(s, saved, "planning preserves the Deferred record");
        }
    }
}

fn r3_zero_budget_keeps_checking_across_ticks_without_dispatching() {
    let mut s = interval();
    s.definitions[0].budget.max_agent_starts = 0;
    for now in [100, 150, 200, 250, 300] {
        let p = plan(&s, now, &limits(1, 0)).unwrap();
        assert_eq!(p.due, vec![check("a", now)]);
        assert_eq!(
            p.held,
            s.runs
                .iter()
                .map(|r| Held {
                    action: Action::Dispatch {
                        run_id: r.id.clone()
                    },
                    reason: HoldReason::Budget,
                })
                .collect::<Vec<_>>()
        );
        let mut found = run(
            &format!("run-{now}"),
            "a",
            Priority::Normal,
            RunResult::Deferred,
        );
        found.wake = Occurrence::Scheduled { due_at_ms: now };
        found.started_at_ms = now;
        found.updated_at_ms = now;
        s.runs.push(found);
    }
    assert_eq!(s.runs.len(), 5);
    assert_eq!(
        s.runs.iter().map(|r| r.id.clone()).collect::<Vec<_>>(),
        vec![
            id("run-100"),
            id("run-150"),
            id("run-200"),
            id("run-250"),
            id("run-300")
        ]
    );
    // Being allowed to check still cannot bypass the shared check limit.
    let p = plan(&s, 350, &limits(0, 0)).unwrap();
    assert_eq!(p.due, vec![]);
    assert_eq!(p.held.len(), 6);
    assert_eq!(
        p.held.last(),
        Some(&Held {
            action: check("a", 350),
            reason: HoldReason::CheckCapacity,
        })
    );
}

fn r3_used_positive_budget_coalesces_until_the_saved_charge_expires() {
    let mut s = interval();
    s.definitions[0].budget = Budget {
        window_ms: nz(100),
        max_agent_starts: 1,
    };
    s.runs
        .push(run("run-100", "a", Priority::Normal, RunResult::Deferred));
    let mut past = run(
        "past",
        "a",
        Priority::Normal,
        RunResult::NotCreated {
            dispatch_at_ms: 150,
        },
    );
    past.definition_revision = text("synthetic-older-revision");
    past.wake = Occurrence::Scheduled { due_at_ms: 50 };
    past.started_at_ms = 50;
    past.updated_at_ms = 150;
    s.runs.push(past);
    for now in [200, 249] {
        assert_eq!(
            plan(&s, now, &limits(1, 0)).unwrap(),
            Plan {
                due: vec![],
                held: vec![
                    Held {
                        action: dispatch(),
                        reason: HoldReason::Budget
                    },
                    Held {
                        action: check("a", 150),
                        reason: HoldReason::WorkPending
                    },
                ],
            },
            "used positive budget at {now}"
        );
    }
    assert_eq!(
        plan(&s, 250, &limits(1, 0)).unwrap(),
        Plan {
            due: vec![dispatch()],
            held: vec![Held {
                action: check("a", 150),
                reason: HoldReason::WorkPending
            }],
        }
    );
}

fn r1_non_deferred_records_do_not_hold_the_next_scheduled_check() {
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
        let mut s = interval();
        s.runs.push(run("run-100", "a", Priority::Normal, result));
        assert_eq!(
            plan(&s, 200, &limits(10, 0)).unwrap(),
            Plan {
                due: vec![check("a", 150)],
                held: vec![],
            },
            "{result:?}"
        );
    }
}
