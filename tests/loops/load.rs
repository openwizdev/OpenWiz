use super::*;
use std::collections::BTreeSet;

#[test]
fn lp2_two_hundred_loops_drain_with_both_shared_limits_and_no_loop_cap() {
    drain(Wake::Once { at_ms: 100 }, 100);
}

#[test]
fn lp2_two_hundred_overdue_intervals_coalesce_without_a_replay_burst() {
    drain(
        Wake::Interval {
            every_ms: nz(50),
            anchor_ms: 100,
        },
        10_000,
    );
}

fn drain(wake: Wake, now_ms: u64) {
    let mut s = snapshot(
        (0..200)
            .map(|n| {
                definition(
                    &format!("loop-syn-{n:03}"),
                    if n % 10 == 0 {
                        Priority::Urgent
                    } else {
                        Priority::Normal
                    },
                )
            })
            .collect(),
    );
    for d in &mut s.definitions {
        d.wake = wake.clone();
    }
    let l = Limits {
        checks: Capacity {
            max: 7,
            urgent_reserve: 2,
        },
        agents: Capacity {
            max: 5,
            urgent_reserve: 1,
        },
    };
    let first = plan(&s, now_ms, &l).unwrap();
    assert_eq!(
        first.due,
        vec![
            check("loop-syn-000", 100),
            check("loop-syn-010", 100),
            check("loop-syn-020", 100),
            check("loop-syn-030", 100),
            check("loop-syn-040", 100),
            check("loop-syn-050", 100),
            check("loop-syn-060", 100)
        ]
    );
    assert_eq!(first.held.len(), 193, "every held loop remains visible");
    let mut checked = BTreeSet::new();
    let mut dispatched = BTreeSet::new();
    for _ in 0..200 {
        let p = plan(&s, now_ms, &l).unwrap();
        assert_eq!(
            p,
            plan(&s, now_ms, &l).unwrap(),
            "the planner has no hidden mutation"
        );
        for action in p.due {
            match action {
                Action::Check {
                    loop_id,
                    revision,
                    occurrence,
                } => {
                    assert!(checked.insert(loop_id.clone()), "one check per occurrence");
                    let d = s.definitions.iter().find(|d| d.id == loop_id).unwrap();
                    s.runs.push(Run {
                        id: id(&format!("run-{}", loop_id.as_str())),
                        loop_id,
                        definition_revision: revision,
                        wake: occurrence,
                        started_at_ms: now_ms,
                        updated_at_ms: now_ms,
                        priority: d.priority,
                        result: RunResult::Checking,
                    });
                }
                Action::Dispatch { run_id } => {
                    assert!(dispatched.insert(run_id.clone()), "one dispatch per run");
                    s.runs.iter_mut().find(|r| r.id == run_id).unwrap().result =
                        RunResult::Dispatching {
                            dispatch_at_ms: now_ms,
                        };
                }
            }
        }
        let checking: Vec<_> = s
            .runs
            .iter()
            .filter(|r| r.result == RunResult::Checking)
            .collect();
        let agents: Vec<_> = s
            .runs
            .iter()
            .filter(|r| matches!(r.result, RunResult::Dispatching { .. }))
            .collect();
        assert!(checking.len() <= 7);
        assert!(
            checking
                .iter()
                .filter(|r| r.priority == Priority::Normal)
                .count()
                <= 5
        );
        assert!(agents.len() <= 5);
        assert!(
            agents
                .iter()
                .filter(|r| r.priority == Priority::Normal)
                .count()
                <= 4
        );
        for r in &mut s.runs {
            r.result = match r.result {
                RunResult::Checking => RunResult::Deferred,
                RunResult::Dispatching { dispatch_at_ms } => RunResult::Created { dispatch_at_ms },
                other => other,
            };
        }
        if dispatched.len() == 200 {
            break;
        }
    }
    assert_eq!(checked.len(), 200);
    assert_eq!(dispatched.len(), 200);
    assert_eq!(s.runs.len(), 200);
    assert!(
        s.runs
            .iter()
            .all(|r| matches!(r.result, RunResult::Created { .. }))
    );
    assert_eq!(
        plan(&s, now_ms, &l).unwrap(),
        Plan::default(),
        "a restart on saved records repeats no work"
    );
}
