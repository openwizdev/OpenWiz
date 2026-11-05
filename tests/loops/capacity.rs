use super::*;

#[test]
fn lp1_capacity_contracts_preserve_shared_check_limits() {
    let cases: [(&str, fn()); 3] = [
        (
            "lp1_existing_checks_count_even_for_disabled_or_removed_loops",
            lp1_existing_checks_count_even_for_disabled_or_removed_loops,
        ),
        (
            "lp1_once_checks_respect_total_and_urgent_reserve",
            lp1_once_checks_respect_total_and_urgent_reserve,
        ),
        (
            "lp1_urgent_never_bypasses_full_capacity",
            lp1_urgent_never_bypasses_full_capacity,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: capacity::{name}");
        proof();
    }
}

fn lp1_once_checks_respect_total_and_urgent_reserve() {
    for (max, reserve, due, held) in [
        (0, 0, vec![], vec!["u", "a", "b", "c"]),
        (1, 1, vec!["u"], vec!["a", "b", "c"]),
        (3, 1, vec!["u", "a", "b"], vec!["c"]),
        (3, 2, vec!["u", "a"], vec!["b", "c"]),
        (4, 0, vec!["u", "a", "b", "c"], vec![]),
    ] {
        let s = snapshot(vec![
            definition("c", Priority::Normal),
            definition("b", Priority::Normal),
            definition("u", Priority::Urgent),
            definition("a", Priority::Normal),
        ]);
        let p = plan(&s, 100, &limits(max, reserve)).unwrap();
        assert_eq!(
            p.due,
            due.iter().map(|s| check(s, 100)).collect::<Vec<_>>(),
            "max={max},reserve={reserve}"
        );
        assert_eq!(
            p.held,
            held.iter()
                .map(|s| Held {
                    action: check(s, 100),
                    reason: HoldReason::CheckCapacity
                })
                .collect::<Vec<_>>()
        );
        let mut reversed = s.clone();
        reversed.definitions.reverse();
        assert_eq!(
            p,
            plan(&reversed, 100, &limits(max, reserve)).unwrap(),
            "input order must not choose a winner"
        );
    }
}

fn lp1_existing_checks_count_even_for_disabled_or_removed_loops() {
    let mut s = snapshot(vec![
        definition("a", Priority::Normal),
        definition("b", Priority::Normal),
        definition("u", Priority::Urgent),
    ]);
    s.runs.push(run(
        "old-check",
        "removed",
        Priority::Normal,
        RunResult::Checking,
    ));
    let p = plan(&s, 100, &limits(3, 1)).unwrap();
    assert_eq!(p.due, vec![check("u", 100), check("a", 100)]);
    assert_eq!(
        p.held,
        vec![Held {
            action: check("b", 100),
            reason: HoldReason::CheckCapacity
        }]
    );
    s.definitions.push({
        let mut d = definition("removed", Priority::Normal);
        d.enabled = false;
        d
    });
    assert_eq!(p, plan(&s, 100, &limits(3, 1)).unwrap());
}

fn lp1_urgent_never_bypasses_full_capacity() {
    let mut s = snapshot(vec![definition("u", Priority::Urgent)]);
    s.runs.push(run(
        "old-check",
        "removed",
        Priority::Urgent,
        RunResult::Checking,
    ));
    assert_eq!(
        plan(&s, 100, &limits(1, 1)).unwrap(),
        Plan {
            due: vec![],
            held: vec![Held {
                action: check("u", 100),
                reason: HoldReason::CheckCapacity
            }]
        }
    );
}
