use super::*;

fn work(names: &[(&str, Priority)]) -> Snapshot {
    let mut s = snapshot(names.iter().map(|(n, p)| definition(n, *p)).collect());
    s.runs = names
        .iter()
        .map(|(n, p)| run(&format!("run-{n}"), n, *p, RunResult::Deferred))
        .collect();
    s
}
fn dispatch(name: &str) -> Action {
    Action::Dispatch {
        run_id: id(&format!("run-{name}")),
    }
}
fn agent_limits(max: usize, reserve: usize) -> Limits {
    Limits {
        agents: Capacity {
            max,
            urgent_reserve: reserve,
        },
        ..limits(3, 1)
    }
}
fn past(result: RunResult) -> Run {
    Run {
        id: id("past"),
        loop_id: id("a"),
        definition_revision: text("synthetic-old-revision"),
        wake: Occurrence::Scheduled { due_at_ms: 0 },
        started_at_ms: 10,
        updated_at_ms: 200,
        priority: Priority::Normal,
        result,
    }
}

#[test]
fn lp1_dispatch_contracts_preserve_capacity_budget_and_refusals() {
    let cases: [(&str, fn()); 9] = [
        (
            "lp1_active_and_unresolved_agents_count_once_and_keep_original_priority",
            lp1_active_and_unresolved_agents_count_once_and_keep_original_priority,
        ),
        (
            "lp1_agent_capacity_and_reserve_table",
            lp1_agent_capacity_and_reserve_table,
        ),
        (
            "lp1_an_expired_budget_charge_does_not_free_an_uncertain_agent_slot",
            lp1_an_expired_budget_charge_does_not_free_an_uncertain_agent_slot,
        ),
        (
            "lp1_budget_charges_saved_attempts_and_expires_by_dispatch_time",
            lp1_budget_charges_saved_attempts_and_expires_by_dispatch_time,
        ),
        (
            "lp1_off_shadow_and_changed_revision_never_dispatch",
            lp1_off_shadow_and_changed_revision_never_dispatch,
        ),
        (
            "lp1_one_pass_charges_each_new_dispatch_against_the_same_loop_budget",
            lp1_one_pass_charges_each_new_dispatch_against_the_same_loop_budget,
        ),
        (
            "lp1_settled_outcomes_never_repeat_a_dispatch",
            lp1_settled_outcomes_never_repeat_a_dispatch,
        ),
        (
            "lp1_unknown_occupancy_holds_dispatch_but_allows_checks",
            lp1_unknown_occupancy_holds_dispatch_but_allows_checks,
        ),
        (
            "lp1_zero_budget_allows_checks_and_never_dispatches",
            lp1_zero_budget_allows_checks_and_never_dispatches,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: dispatch::{name}");
        proof();
    }
}

fn lp1_agent_capacity_and_reserve_table() {
    for (max, reserve, due, held) in [
        (0, 0, vec![], vec!["u", "a", "b", "c"]),
        (1, 1, vec!["u"], vec!["a", "b", "c"]),
        (3, 1, vec!["u", "a", "b"], vec!["c"]),
        (3, 2, vec!["u", "a"], vec!["b", "c"]),
        (4, 0, vec!["u", "a", "b", "c"], vec![]),
    ] {
        let s = work(&[
            ("c", Priority::Normal),
            ("a", Priority::Normal),
            ("u", Priority::Urgent),
            ("b", Priority::Normal),
        ]);
        let p = plan(&s, 200, &agent_limits(max, reserve)).unwrap();
        assert_eq!(p.due, due.iter().map(|n| dispatch(n)).collect::<Vec<_>>());
        assert_eq!(
            p.held,
            held.iter()
                .map(|n| Held {
                    action: dispatch(n),
                    reason: HoldReason::AgentCapacity
                })
                .collect::<Vec<_>>()
        );
        let mut reverse = s.clone();
        reverse.runs.reverse();
        reverse.definitions.reverse();
        assert_eq!(p, plan(&reverse, 200, &agent_limits(max, reserve)).unwrap());
    }
}

fn lp1_active_and_unresolved_agents_count_once_and_keep_original_priority() {
    let mut s = work(&[
        ("a", Priority::Normal),
        ("b", Priority::Normal),
        ("u", Priority::Urgent),
    ]);
    for result in [
        RunResult::Created {
            dispatch_at_ms: 100,
        },
        RunResult::Dispatching {
            dispatch_at_ms: 100,
        },
        RunResult::Uncertain {
            dispatch_at_ms: 100,
        },
    ] {
        s.runs.retain(|r| r.loop_id != id("removed"));
        s.runs
            .push(run("old-agent", "removed", Priority::Normal, result));
        s.active_agents = Some(vec![ActiveAgent {
            run_id: id("old-agent"),
        }]);
        let p = plan(&s, 200, &agent_limits(3, 1)).unwrap();
        assert_eq!(p.due, vec![dispatch("u"), dispatch("a")], "{result:?}");
        assert_eq!(
            p.held,
            vec![Held {
                action: dispatch("b"),
                reason: HoldReason::AgentCapacity
            }]
        );
    }
    s.active_agents = Some(vec![]);
    assert_eq!(
        plan(&s, 200, &agent_limits(1, 0)).unwrap().due,
        vec![],
        "uncertain still occupies a slot without positive active observation"
    );
    s.runs.last_mut().unwrap().result = RunResult::Created {
        dispatch_at_ms: 100,
    };
    assert_eq!(
        plan(&s, 200, &agent_limits(1, 0)).unwrap().due,
        vec![dispatch("u")],
        "historical created alone is not occupancy"
    );
}

fn lp1_unknown_occupancy_holds_dispatch_but_allows_checks() {
    let mut s = work(&[("a", Priority::Urgent)]);
    s.definitions.push(definition("check", Priority::Normal));
    s.active_agents = None;
    let p = plan(&s, 200, &agent_limits(3, 1)).unwrap();
    assert_eq!(p.due, vec![check("check", 100)]);
    assert_eq!(
        p.held,
        vec![Held {
            action: dispatch("a"),
            reason: HoldReason::AgentOccupancyUnknown
        }]
    );
}

fn lp1_budget_charges_saved_attempts_and_expires_by_dispatch_time() {
    let charged = [
        RunResult::Dispatching {
            dispatch_at_ms: 150,
        },
        RunResult::Created {
            dispatch_at_ms: 150,
        },
        RunResult::NotCreated {
            dispatch_at_ms: 150,
        },
        RunResult::Uncertain {
            dispatch_at_ms: 150,
        },
    ];
    let uncharged = [
        RunResult::Quiet,
        RunResult::CheckFailed,
        RunResult::CheckTimedOut,
        RunResult::Shadow,
        RunResult::Refused,
    ];
    for (result, expected) in charged
        .into_iter()
        .map(|r| (r, false))
        .chain(uncharged.into_iter().map(|r| (r, true)))
    {
        let mut s = work(&[("a", Priority::Urgent)]);
        s.definitions[0].budget = Budget {
            window_ms: nz(100),
            max_agent_starts: 1,
        };
        s.runs.push(past(result));
        let p = plan(&s, 200, &agent_limits(10, 0)).unwrap();
        assert_eq!(
            p.due,
            if expected {
                vec![dispatch("a")]
            } else {
                vec![]
            },
            "{result:?}"
        );
        assert_eq!(
            p.held,
            if expected {
                vec![]
            } else {
                vec![Held {
                    action: dispatch("a"),
                    reason: HoldReason::Budget,
                }]
            }
        );
    }
    // The rolling interval is (now-window, now]; the saved dispatch mark,
    // not the later result update, determines when a charge expires.
    for (at, expected) in [(99, true), (100, true), (101, false), (200, false)] {
        let mut s = work(&[("a", Priority::Normal)]);
        s.definitions[0].budget = Budget {
            window_ms: nz(100),
            max_agent_starts: 1,
        };
        s.runs
            .push(past(RunResult::NotCreated { dispatch_at_ms: at }));
        assert_eq!(
            plan(&s, 200, &agent_limits(10, 0)).unwrap().due,
            if expected {
                vec![dispatch("a")]
            } else {
                vec![]
            },
            "saved={at}"
        );
    }
}

fn lp1_zero_budget_allows_checks_and_never_dispatches() {
    let mut s = work(&[("a", Priority::Urgent)]);
    s.definitions[0].budget.max_agent_starts = 0;
    let mut d = definition("b", Priority::Normal);
    d.budget.max_agent_starts = 0;
    s.definitions.push(d);
    assert_eq!(
        plan(&s, 200, &limits(2, 0)).unwrap(),
        Plan {
            due: vec![check("b", 100)],
            held: vec![Held {
                action: dispatch("a"),
                reason: HoldReason::Budget
            }]
        }
    );
}

fn lp1_off_shadow_and_changed_revision_never_dispatch() {
    for (change, reason) in [
        (0, HoldReason::Disabled),
        (1, HoldReason::Shadow),
        (2, HoldReason::RevisionChanged),
    ] {
        let mut s = work(&[("a", Priority::Normal)]);
        match change {
            0 => s.definitions[0].enabled = false,
            1 => s.definitions[0].mode = Mode::Shadow,
            _ => s.definitions[0].revision = text("synthetic-revision-2"),
        }
        let p = plan(&s, 200, &agent_limits(10, 0)).unwrap();
        assert_eq!(p.due, vec![]);
        assert_eq!(
            p.held,
            vec![Held {
                action: dispatch("a"),
                reason
            }]
        );
    }
}

fn lp1_settled_outcomes_never_repeat_a_dispatch() {
    for result in [
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
        let mut s = work(&[("a", Priority::Normal)]);
        s.runs[0].result = result;
        assert_eq!(
            plan(&s, 200, &agent_limits(10, 0)).unwrap(),
            Plan::default(),
            "{result:?}"
        );
    }
}

fn lp1_one_pass_charges_each_new_dispatch_against_the_same_loop_budget() {
    let mut s = work(&[("a", Priority::Normal)]);
    s.definitions[0].wake = Wake::Event {
        event: Event::CheckSuite,
    };
    s.definitions[0].budget.max_agent_starts = 1;
    s.runs[0].wake = Occurrence::Event {
        event: Event::CheckSuite,
        event_id: text("synthetic-event-a"),
    };
    let mut second = s.runs[0].clone();
    second.id = id("run-b");
    second.wake = Occurrence::Event {
        event: Event::CheckSuite,
        event_id: text("synthetic-event-b"),
    };
    s.runs.push(second);
    let p = plan(&s, 200, &agent_limits(10, 0)).unwrap();
    assert_eq!(p.due, vec![dispatch("a")]);
    assert_eq!(
        p.held,
        vec![Held {
            action: dispatch("b"),
            reason: HoldReason::Budget
        }]
    );
    s.runs.reverse();
    assert_eq!(p, plan(&s, 200, &agent_limits(10, 0)).unwrap());
}

fn lp1_an_expired_budget_charge_does_not_free_an_uncertain_agent_slot() {
    let mut s = work(&[("a", Priority::Urgent)]);
    s.definitions[0].budget = Budget {
        window_ms: nz(100),
        max_agent_starts: 1,
    };
    s.runs
        .push(past(RunResult::Uncertain { dispatch_at_ms: 50 }));
    let p = plan(&s, 200, &agent_limits(1, 0)).unwrap();
    assert_eq!(p.due, vec![]);
    assert_eq!(
        p.held,
        vec![Held {
            action: dispatch("a"),
            reason: HoldReason::AgentCapacity
        }]
    );
}
