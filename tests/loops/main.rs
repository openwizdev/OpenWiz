//! LP1/LP2, synthetic inputs through the public core planner; no I/O or
//! real clock. These tests do not prove executor or live loop behavior.
mod capacity;
mod deferred;
mod dispatch;
mod guards;
mod l6_api;
mod l6_cli;
mod l6_config;
mod l6_switches;
mod load;
mod missed;
mod schedules;

use openwiz_core::loops::*;
use std::num::NonZeroU64;

fn id(s: &str) -> OpId {
    OpId::parse(s).unwrap()
}
fn text(s: &str) -> NonEmpty {
    NonEmpty::new(s).unwrap()
}
fn nz(n: u64) -> NonZeroU64 {
    NonZeroU64::new(n).unwrap()
}
fn definition(name: &str, priority: Priority) -> Definition {
    Definition {
        id: id(name),
        revision: text("synthetic-revision-1"),
        wake: Wake::Once { at_ms: 100 },
        enabled: true,
        mode: Mode::Active,
        priority,
        budget: Budget {
            window_ms: nz(1000),
            max_agent_starts: 10,
        },
    }
}
fn snapshot(definitions: Vec<Definition>) -> Snapshot {
    Snapshot {
        definitions,
        runs: vec![],
        active_agents: Some(vec![]),
    }
}
fn limits(checks: usize, reserve: usize) -> Limits {
    Limits {
        checks: Capacity {
            max: checks,
            urgent_reserve: reserve,
        },
        agents: Capacity {
            max: 3,
            urgent_reserve: 1,
        },
    }
}
fn check(name: &str, due_at_ms: u64) -> Action {
    Action::Check {
        loop_id: id(name),
        revision: text("synthetic-revision-1"),
        occurrence: Occurrence::Scheduled { due_at_ms },
    }
}
fn run(name: &str, loop_name: &str, priority: Priority, result: RunResult) -> Run {
    Run {
        id: id(name),
        loop_id: id(loop_name),
        definition_revision: text("synthetic-revision-1"),
        wake: Occurrence::Scheduled { due_at_ms: 100 },
        started_at_ms: 100,
        updated_at_ms: 100,
        priority,
        result,
    }
}
