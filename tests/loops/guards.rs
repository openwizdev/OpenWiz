use super::*;

fn valid() -> Snapshot {
    let mut s = snapshot(vec![
        definition("a", Priority::Normal),
        definition("b", Priority::Urgent),
    ]);
    s.runs
        .push(run("run-a", "a", Priority::Normal, RunResult::Deferred));
    s
}

#[test]
fn lp1_snapshot_contracts_preserve_closed_admission() {
    let cases: [(&str, fn()); 3] = [
        (
            "lp1_ambiguous_or_impossible_snapshots_fail_closed",
            lp1_ambiguous_or_impossible_snapshots_fail_closed,
        ),
        (
            "lp1_removed_deferred_work_is_reported_and_never_dispatched",
            lp1_removed_deferred_work_is_reported_and_never_dispatched,
        ),
        (
            "lp1_reserve_cannot_exceed_total_capacity",
            lp1_reserve_cannot_exceed_total_capacity,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: guards::{name}");
        proof();
    }
}

fn lp1_ambiguous_or_impossible_snapshots_fail_closed() {
    let mut cases = Vec::new();
    let mut s = valid();
    s.definitions.push(s.definitions[0].clone());
    cases.push(("duplicate definition", s));
    let mut s = valid();
    s.runs.push(s.runs[0].clone());
    cases.push(("duplicate run id", s));
    let mut s = valid();
    let mut r = s.runs[0].clone();
    r.id = id("different-run");
    s.runs.push(r);
    cases.push(("duplicate occurrence across run ids", s));
    let mut s = valid();
    s.runs[0].started_at_ms = 201;
    cases.push(("future admission", s));
    let mut s = valid();
    s.runs[0].updated_at_ms = 201;
    cases.push(("future update", s));
    let mut s = valid();
    s.runs[0].updated_at_ms = 99;
    cases.push(("update before start", s));
    let mut s = valid();
    s.runs[0].wake = Occurrence::Scheduled { due_at_ms: 101 };
    cases.push(("occurrence after start", s));
    let mut s = valid();
    s.runs[0].priority = Priority::Urgent;
    cases.push(("wrong priority for immutable revision", s));
    let mut s = valid();
    s.runs[0].wake = Occurrence::Scheduled { due_at_ms: 99 };
    cases.push(("wrong once occurrence", s));
    let mut s = valid();
    s.runs[0].wake = Occurrence::Event {
        event: Event::CheckSuite,
        event_id: text("synthetic-event"),
    };
    cases.push(("event does not match definition", s));
    let mut s = valid();
    s.definitions[0].revision = text(" \t");
    cases.push(("blank revision", s));
    let mut s = valid();
    s.runs[0].definition_revision = text("bad\0revision");
    cases.push(("NUL revision", s));
    let mut s = valid();
    s.runs[0].result = RunResult::Dispatching { dispatch_at_ms: 99 };
    cases.push(("dispatch before admission", s));
    let mut s = valid();
    s.runs[0].result = RunResult::Uncertain {
        dispatch_at_ms: 101,
    };
    cases.push(("dispatch after latest update", s));
    let mut s = valid();
    s.active_agents = Some(vec![ActiveAgent {
        run_id: id("missing-run"),
    }]);
    cases.push(("unmatched active agent", s));
    let mut s = valid();
    s.active_agents = Some(vec![ActiveAgent {
        run_id: id("run-a"),
    }]);
    cases.push(("active agent without dispatch", s));
    let mut s = valid();
    s.runs[0].result = RunResult::NotCreated {
        dispatch_at_ms: 100,
    };
    s.active_agents = Some(vec![ActiveAgent {
        run_id: id("run-a"),
    }]);
    cases.push(("agent contradicts no creation", s));
    let mut s = valid();
    s.runs[0].result = RunResult::Created {
        dispatch_at_ms: 100,
    };
    s.active_agents = Some(vec![
        ActiveAgent {
            run_id: id("run-a"),
        },
        ActiveAgent {
            run_id: id("run-a"),
        },
    ]);
    cases.push(("duplicate active observation", s));
    for (name, s) in cases {
        assert_eq!(
            plan(&s, 200, &limits(3, 1)),
            Err(PlanError::InvalidSnapshot),
            "{name}"
        );
    }
}

fn lp1_reserve_cannot_exceed_total_capacity() {
    for l in [
        limits(1, 2),
        Limits {
            agents: Capacity {
                max: 0,
                urgent_reserve: 1,
            },
            ..limits(3, 1)
        },
    ] {
        assert_eq!(plan(&valid(), 200, &l), Err(PlanError::InvalidLimits));
    }
}

fn lp1_removed_deferred_work_is_reported_and_never_dispatched() {
    let mut s = valid();
    s.definitions.remove(0);
    let p = plan(&s, 200, &limits(3, 1)).unwrap();
    assert_eq!(p.due, vec![check("b", 100)]);
    assert_eq!(
        p.held,
        vec![Held {
            action: Action::Dispatch {
                run_id: id("run-a")
            },
            reason: HoldReason::DefinitionMissing
        }]
    );
}
