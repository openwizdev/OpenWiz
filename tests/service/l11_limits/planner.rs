use super::*;
use std::collections::BTreeSet;

fn snapshot(urgent: usize) -> Snapshot {
    Snapshot {
        definitions: (0..200)
            .map(|n| {
                definition(
                    n,
                    if n < urgent {
                        Priority::Urgent
                    } else {
                        Priority::Normal
                    },
                )
            })
            .collect(),
        runs: vec![],
        active_agents: Some(vec![]),
    }
}
#[test]
fn planner_reserves_and_saturation() {
    let limits = approved();
    for (urgent, checks, agents) in [(0, 3, 12), (1, 4, 13), (4, 4, 16), (200, 4, 16)] {
        let mut s = snapshot(urgent);
        let p = plan(&s, 100, &limits).unwrap();
        assert_eq!(p.due.len(), checks);
        assert_eq!(p.held.len(), 200 - checks);
        assert!(p.held.iter().all(|h| h.reason == HoldReason::CheckCapacity));
        s.runs = s
            .definitions
            .iter()
            .map(|d| run(d, RunResult::Deferred))
            .collect();
        let p = plan(&s, 100, &limits).unwrap();
        assert_eq!(p.due.len(), agents);
        assert_eq!(p.held.len(), 200 - agents);
        assert!(p.held.iter().all(|h| h.reason == HoldReason::AgentCapacity));
    }
    // Existing work consumes its own normal/urgent portions and total slots.
    for (priority, occupied, expected_checks, expected_agents) in [
        (Priority::Normal, 3, 1, 13),
        (Priority::Urgent, 4, 0, 12),
        (Priority::Normal, 12, 0, 4),
        (Priority::Urgent, 16, 0, 0),
    ] {
        let mut s = snapshot(200);
        for n in 200..200 + occupied {
            s.runs
                .push(run(&definition(n, priority), RunResult::Checking));
        }
        assert_eq!(plan(&s, 100, &limits).unwrap().due.len(), expected_checks);
        s.runs = s
            .definitions
            .iter()
            .map(|d| run(d, RunResult::Deferred))
            .collect();
        for n in 200..200 + occupied {
            s.runs.push(run(
                &definition(n, priority),
                RunResult::Dispatching {
                    dispatch_at_ms: 100,
                },
            ));
        }
        assert_eq!(plan(&s, 100, &limits).unwrap().due.len(), expected_agents);
    }
}
#[test]
fn two_hundred_loops_drain() {
    let limits = approved();
    let mut s = snapshot(20);
    let mut checked = BTreeSet::new();
    let mut dispatched = BTreeSet::new();
    for _ in 0..200 {
        let p = plan(&s, 100, &limits).unwrap();
        let mut checks = 0;
        let mut normal_checks = 0;
        let mut agents = 0;
        let mut normal_agents = 0;
        for action in p.due {
            match action {
                Action::Check { loop_id, .. } => {
                    assert!(checked.insert(loop_id.clone()));
                    let d = s.definitions.iter().find(|d| d.id == loop_id).unwrap();
                    checks += 1;
                    normal_checks += usize::from(d.priority == Priority::Normal);
                    s.runs.push(run(d, RunResult::Deferred));
                }
                Action::Dispatch { run_id } => {
                    assert!(dispatched.insert(run_id.clone()));
                    let r = s.runs.iter_mut().find(|r| r.id == run_id).unwrap();
                    agents += 1;
                    normal_agents += usize::from(r.priority == Priority::Normal);
                    r.result = RunResult::Created {
                        dispatch_at_ms: 100,
                    };
                }
            }
        }
        assert!(checks <= 4 && normal_checks <= 3);
        assert!(agents <= 16 && normal_agents <= 12);
        if dispatched.len() == 200 {
            break;
        }
    }
    assert_eq!(checked.len(), 200);
    assert_eq!(dispatched.len(), 200);
    assert_eq!(s.runs.len(), 200);
    assert_eq!(plan(&s, 100, &limits).unwrap(), Plan::default());
}
#[test]
fn planner_budget_and_uncertainty() {
    let limits = approved();
    let mut s = snapshot(0);
    s.runs = s
        .definitions
        .iter()
        .map(|d| run(d, RunResult::Deferred))
        .collect();
    s.active_agents = None;
    let p = plan(&s, 100, &limits).unwrap();
    assert!(p.due.is_empty());
    assert_eq!(p.held.len(), 200);
    assert!(
        p.held
            .iter()
            .all(|h| h.reason == HoldReason::AgentOccupancyUnknown)
    );
    s.active_agents = Some(vec![]);
    for n in 200..212 {
        let r = run(
            &definition(n, Priority::Normal),
            if n % 2 == 0 {
                RunResult::Uncertain {
                    dispatch_at_ms: 100,
                }
            } else {
                RunResult::Dispatching {
                    dispatch_at_ms: 100,
                }
            },
        );
        s.active_agents.as_mut().unwrap().push(ActiveAgent {
            run_id: r.id.clone(),
        });
        s.runs.push(r);
    }
    assert!(plan(&s, 100, &limits).unwrap().due.is_empty());
    // The same unsettled run in both observations counts once.
    s.definitions[0].priority = Priority::Urgent;
    s.runs[0].priority = Priority::Urgent;
    assert_eq!(
        plan(&s, 100, &limits).unwrap().due,
        vec![Action::Dispatch {
            run_id: s.runs[0].id.clone()
        }]
    );

    for result in [
        RunResult::Uncertain {
            dispatch_at_ms: 100,
        },
        RunResult::Dispatching {
            dispatch_at_ms: 100,
        },
        RunResult::NotCreated {
            dispatch_at_ms: 100,
        },
        RunResult::Created {
            dispatch_at_ms: 100,
        },
    ] {
        let mut d = definition(0, Priority::Normal);
        d.wake = Wake::Interval {
            every_ms: NonZeroU64::new(100).unwrap(),
            anchor_ms: 100,
        };
        let old = run(&d, result);
        let mut pending = run(&d, RunResult::Deferred);
        pending.id = id("later-run");
        pending.wake = Occurrence::Scheduled { due_at_ms: 200 };
        pending.started_at_ms = 200;
        pending.updated_at_ms = 200;
        let s = Snapshot {
            definitions: vec![d],
            runs: vec![old, pending.clone()],
            active_agents: Some(vec![]),
        };
        let before = plan(&s, 1099, &limits).unwrap();
        assert!(before.held.iter().any(|h| h.action
            == Action::Dispatch {
                run_id: pending.id.clone()
            }
            && h.reason == HoldReason::Budget));
        let after = plan(&s, 1100, &limits).unwrap();
        assert!(after.due.contains(&Action::Dispatch { run_id: pending.id }));
    }
}
