//! The read-only `fleet tick --dry-run` and GitHub-only `fleet due` (B5, #121).
//! The executing tick and `--expect-plan` were retired (#800, spec #786).
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_adapter_github::tick::TickReads;
use openwiz_core::fleet::model::Number;
use openwiz_core::fleet::tick::{self, Detail, Kind, Observed};
use openwiz_core::ops::Clock;
use std::collections::BTreeSet;
use std::ffi::OsString;
use std::io::Write;
use std::path::Path;

#[path = "fleet_tick_graph.rs"]
mod graph;
pub use graph::{Inventory, World};
#[path = "fleet_tick_records.rs"]
mod records;

pub const USAGE: &str =
    "  openwiz fleet tick --dry-run [--json]\n  openwiz fleet due --github-only [--json]\n";
pub const HELP: &str = "fleet tick --dry-run\n  Plan every fleet from GitHub, CloudRoom and OpenWiz start records, and print the\n  plan. It reads only: no locks, writes, starts or messages. Only judgment items are\n  printed; --json prints the whole openwiz.fleet-tick.v1 plan. Without --dry-run it\n  refuses: the executing tick was retired.\nfleet due --github-only\n  A read-only GitHub candidate check for a loop sandbox without room-cli. One line\n  per possible action, silent when idle. A failed global read exits 1. The agent\n  it wakes verifies CloudRoom facts before acting.\n  --json prints openwiz.fleet-due.v1 candidates, including an empty list.\n";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Args {
    pub due: bool,
    pub dry_run: bool,
    pub json: bool,
}
pub fn parse(args: &[OsString]) -> Result<Args, &'static str> {
    let Some(command) = args.first().and_then(|s| s.to_str()) else {
        return Err("missing fleet command");
    };
    let mut a = Args {
        due: command == "due",
        dry_run: false,
        json: false,
    };
    if !["tick", "due"].contains(&command) {
        return Err("unknown fleet command");
    }
    let mut github = false;
    for arg in &args[1..] {
        match arg.to_str() {
            Some("--dry-run") if !a.due && !a.dry_run => a.dry_run = true,
            Some("--json") if !a.json => a.json = true,
            Some("--github-only") if a.due && !github => github = true,
            _ => return Err("invalid or repeated fleet option"),
        }
    }
    if a.due && !github {
        return Err("due requires --github-only");
    }
    if !a.due && !a.dry_run {
        return Err("tick requires --dry-run: the executing tick was retired");
    }
    Ok(a)
}
pub fn run(args: &[OsString], out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    let args = match parse(args) {
        Ok(a) => a,
        Err(s) => {
            let _ = writeln!(err, "openwiz: fleet: {s}");
            return crate::EXIT_USAGE;
        }
    };
    match run_inner(args, out) {
        Ok(()) => crate::EXIT_OK,
        Err(s) => {
            let _ = writeln!(err, "openwiz: fleet: {s}");
            crate::EXIT_READ_FAILED
        }
    }
}
fn run_inner(args: Args, out: &mut dyn Write) -> Result<(), &'static str> {
    let gh = TickReads::from_path();
    let clock = crate::SystemClock;
    let deadline = clock.monotonic() + openwiz_core::limits::RUN_BUDGET;
    let inventory = graph::Inventory::read(&gh, deadline)?;
    if args.due && inventory.is_empty() {
        return print_candidates(args.json, &BTreeSet::new(), out);
    }
    let state = if args.due {
        std::path::PathBuf::new()
    } else {
        crate::state::default_state_dir(&|n| std::env::var_os(n))
            .map_err(|_| "state path unavailable")?
    };
    let room = CloudRoomSource::from_path();
    run_observed(args, &gh, &room, &state, deadline, inventory, out)
}

fn run_observed(
    args: Args,
    gh: &TickReads,
    room: &CloudRoomSource,
    state: &Path,
    deadline: std::time::Instant,
    inventory: graph::Inventory,
    out: &mut dyn Write,
) -> Result<(), &'static str> {
    let clock = crate::SystemClock;
    let world = graph::World::read(
        gh,
        if args.due { None } else { Some(room) },
        state,
        deadline,
        inventory,
    )?;
    let now = u64::try_from(clock.now().0).map_err(|_| "clock before epoch")?;
    let plan =
        tick::plan(&world.snapshot, &world.rules, now).map_err(|_| "fleet plan unavailable")?;
    if args.due {
        let mut candidates = plan
            .actions
            .iter()
            .map(|a| (a.spec, a.ticket))
            .collect::<BTreeSet<_>>();
        // Approval reports are candidates here, never merge authority: only
        // the agent it wakes can verify the reviewer's own CloudRoom output. Only the latest
        // report counts, as the planner decides (largest comment id), so a
        // superseded APPROVE never wakes the loop (#852).
        if let Observed::Complete(fleets) = &world.snapshot.fleets {
            for f in fleets {
                if let Observed::Complete(facts) = &f.facts {
                    for t in &facts.tickets {
                        if world.issues.get(&t.number).is_some_and(|i| {
                            i.state == openwiz_core::fleet::model::IssueState::Closed
                        }) && !world
                            .comments
                            .get(&t.number)
                            .is_some_and(|cs| records::has(cs, "launch-fleet: archived"))
                        {
                            candidates.insert((f.spec, Some(t.number)));
                        }
                        if let Observed::Complete(tf) = &t.facts
                            && let Some(tick::PrInput::Open(p)) = &tf.pr
                            && p.reports.iter().max_by_key(|r| r.comment).is_some_and(|r| {
                                r.text.lines().next().is_some_and(|l| {
                                    l == format!(
                                        "VERDICT: APPROVE at {}",
                                        p.fields.head_commit.as_str()
                                    )
                                })
                            })
                            && !p.records.merge_blocked.contains(&p.fields.head_commit)
                        {
                            candidates.insert((f.spec, Some(t.number)));
                        }
                    }
                }
            }
        }
        return print_candidates(args.json, &candidates, out);
    }

    let doc = serde_json::to_value(&plan).map_err(|_| "plan encoding failed")?;
    if args.json {
        serde_json::to_writer_pretty(&mut *out, &doc).map_err(|_| "output failed")?;
        writeln!(out).map_err(|_| "output failed")?;
    } else {
        for action in &plan.actions {
            let who = action.ticket.unwrap_or(action.spec);
            if matches!(action.kind, Kind::Wake | Kind::NeedsYou) {
                let rule = match &action.detail {
                    Detail::Restart {
                        branch, settings, ..
                    } => format!(
                        "restart: branch {} with --provider {} --model {} --reasoning-level {}",
                        branch.as_str(),
                        settings.harness,
                        settings.model,
                        settings.effort
                    ),
                    Detail::Look { reason } => format!("look: {}", crate::clean(reason)),
                    _ => {
                        serde_json::to_value(&action.detail).map_err(|_| "encoding failed")?["rule"]
                            .as_str()
                            .ok_or("rule missing")?
                            .into()
                    }
                };
                writeln!(out, "fleet #{}: #{who} {rule}", action.spec)
                    .map_err(|_| "output failed")?;
            }
        }
    }
    Ok(())
}

fn print_candidates(
    json: bool,
    candidates: &BTreeSet<(Number, Option<Number>)>,
    out: &mut dyn Write,
) -> Result<(), &'static str> {
    if json {
        let candidates: Vec<_> = candidates
            .iter()
            .map(|(spec, ticket)| serde_json::json!({"spec": spec, "ticket": ticket}))
            .collect();
        writeln!(
            out,
            "{}",
            serde_json::json!({"schema": "openwiz.fleet-due.v1", "candidates": candidates})
        )
        .map_err(|_| "output failed")?;
    } else {
        for (spec, ticket) in candidates {
            writeln!(
                out,
                "fleet #{spec}: candidate {}",
                ticket.map_or_else(|| "spec".into(), |n| format!("#{n}"))
            )
            .map_err(|_| "output failed")?;
        }
    }
    Ok(())
}
