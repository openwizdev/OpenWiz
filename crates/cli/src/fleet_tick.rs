//! `fleet tick` and GitHub-only `fleet due` (B5, #121).
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_adapter_github::tick::TickReads;
use openwiz_core::fleet::model::Number;
use openwiz_core::fleet::tick::{self, Detail, Kind, Observed};
use openwiz_core::ops::Clock;
use std::collections::BTreeSet;
use std::ffi::OsString;
use std::io::Write;
use std::path::{Path, PathBuf};

#[path = "fleet_tick_execute.rs"]
mod execute;
#[path = "fleet_tick_graph.rs"]
mod graph;
pub use graph::{Inventory, World};
#[path = "fleet_tick_records.rs"]
mod records;

pub const USAGE: &str = "  openwiz fleet tick [--dry-run | --expect-plan PATH] [--json]\n  openwiz fleet due --github-only [--json]\n";
pub const HELP: &str = "fleet tick\n  Plan every fleet from GitHub and OpenWiz start records, then execute through the\n  allowlisted adapters. Only judgment items, and every action that did not end\n  done, are printed; --json prints private execution facts\n  and outcomes, including thread identities. --dry-run reads only: no locks, writes, starts or messages.\n  --expect-plan PATH requires the exact reviewed --dry-run --json plan before any effect.\n  Pending recovery or any changed action/order/rules/default branch refuses; only the\n  timestamp is validated without comparison. Cannot be combined with --dry-run.\n  OPENWIZ_ORCHESTRATOR_THREAD_ID supplies the destination for Needs you messages.\nfleet due --github-only\n  A read-only GitHub candidate check for a loop sandbox without room-cli. One line\n  per possible action, silent when idle. A failed global read exits 1. The agent\n  it wakes runs fleet tick and verifies CloudRoom facts before acting.\n  --json prints openwiz.fleet-due.v1 candidates, including an empty list.\n";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Args {
    pub due: bool,
    pub dry_run: bool,
    pub json: bool,
}
/// Parsed CLI options retain the restriction; service Args remain unchanged.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParsedArgs {
    pub due: bool,
    pub dry_run: bool,
    pub json: bool,
    pub expect_plan: Option<PathBuf>,
}
pub fn parse(args: &[OsString]) -> Result<ParsedArgs, &'static str> {
    let Some(command) = args.first().and_then(|s| s.to_str()) else {
        return Err("missing fleet command");
    };
    let mut a = ParsedArgs {
        due: command == "due",
        dry_run: false,
        json: false,
        expect_plan: None,
    };
    if !["tick", "due"].contains(&command) {
        return Err("unknown fleet command");
    }
    let mut github = false;
    let mut options = args[1..].iter();
    while let Some(arg) = options.next() {
        match arg.to_str() {
            Some("--dry-run") if !a.due && !a.dry_run => a.dry_run = true,
            Some("--json") if !a.json => a.json = true,
            Some("--github-only") if a.due && !github => github = true,
            Some("--expect-plan") if !a.due && a.expect_plan.is_none() => {
                let path = options
                    .next()
                    .and_then(|s| s.to_str())
                    .filter(|s| !s.is_empty())
                    .ok_or("--expect-plan requires a UTF-8 path")?;
                a.expect_plan = Some(PathBuf::from(path));
            }
            _ => return Err("invalid or repeated fleet option"),
        }
    }
    if a.due && !github {
        return Err("due requires --github-only");
    }
    if a.dry_run && a.expect_plan.is_some() {
        return Err("--expect-plan cannot be combined with --dry-run");
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
fn read_expected(path: &Path) -> Result<serde_json::Value, &'static str> {
    use openwiz_adapter_github::tick::{document, object};
    let bytes = std::fs::read(path).map_err(|_| "reviewed plan file unread")?;
    let expected = document(&bytes).map_err(|_| "reviewed plan JSON invalid")?;
    object(
        &expected,
        &[
            "schema",
            "mode",
            "planned_at",
            "default_branch",
            "rules",
            "actions",
        ],
    )
    .map_err(|_| "reviewed plan fields invalid")?;
    if expected["schema"] != "openwiz.fleet-tick.v1"
        || expected["mode"] != "dry_run"
        || expected["planned_at"].as_u64().is_none()
    {
        return Err("reviewed plan must be a timestamped dry-run envelope");
    }
    // Remaining fields, including every nested key/type, are checked by exact
    // equality against the typed planner's complete document before dispatch.
    Ok(expected)
}

fn run_inner(parsed: ParsedArgs, out: &mut dyn Write) -> Result<(), &'static str> {
    let expected = parsed
        .expect_plan
        .as_deref()
        .map(read_expected)
        .transpose()?;
    let args = Args {
        due: parsed.due,
        dry_run: parsed.dry_run,
        json: parsed.json,
    };
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
        openwiz_store::default_state_dir(&|n| std::env::var_os(n))
            .map_err(|_| "state path unavailable")?
    };
    let room = CloudRoomSource::from_path();
    let orchestrator = std::env::var("OPENWIZ_ORCHESTRATOR_THREAD_ID").ok();
    run_observed(
        args,
        Context {
            github: &gh,
            room: &room,
            state: &state,
            orchestrator: orchestrator.as_deref(),
        },
        deadline,
        inventory,
        out,
        None,
        expected.as_ref(),
    )
}

/// Explicit tick composition for the service. No environment is read for the
/// GitHub executor, state directory or orchestrator destination on this path.
pub struct Context<'a> {
    pub github: &'a TickReads,
    pub room: &'a CloudRoomSource,
    pub state: &'a std::path::Path,
    pub orchestrator: Option<&'a str>,
}

/// Trusted service control. Stop is cooperative; in-flight actions retain
/// their ordinary durable outcomes. The scheduler must confirm completion.
pub struct Control {
    pub stop: std::sync::Arc<std::sync::atomic::AtomicBool>,
    project: String,
    fleet_authority: Option<std::sync::Arc<dyn Fn(Number) -> bool + Send + Sync>>,
    completion_verifier: Option<CompletionVerifier>,
}
/// #2379: re-run at each summary/close effect boundary; `Ok` only when verified.
type CompletionVerifier = std::sync::Arc<dyn Fn(&Detail) -> Result<(), &'static str> + Send + Sync>;
impl Control {
    pub fn new(
        project: &str,
        stop: std::sync::Arc<std::sync::atomic::AtomicBool>,
    ) -> Result<Self, &'static str> {
        openwiz_adapter_cloudroom::allowlist::ThreadId::parse(project)
            .map_err(|_| "invalid configured project")?;
        Ok(Self {
            stop,
            project: project.to_owned(),
            fleet_authority: None,
            completion_verifier: None,
        })
    }
    pub fn project(&self) -> &str {
        &self.project
    }
    /// Read shared service authority at each action boundary, including
    /// recovery. An already dispatched action retains its normal readbacks.
    pub fn with_fleet_authority(
        mut self,
        authority: impl Fn(Number) -> bool + Send + Sync + 'static,
    ) -> Self {
        self.fleet_authority = Some(std::sync::Arc::new(authority));
        self
    }
    /// The trusted completion verifier (#2377 CP1), called afresh at every
    /// summary/close effect boundary. Without one, completion stays refused.
    pub fn with_completion_verifier(
        mut self,
        verifier: impl Fn(&Detail) -> Result<(), &'static str> + Send + Sync + 'static,
    ) -> Self {
        self.completion_verifier = Some(std::sync::Arc::new(verifier));
        self
    }
}
impl Control {
    // Positive completion needs a verifier that re-reads CP1 for this exact
    // effect now. A scheduled tick cannot infer acceptance from closed tickets.
    pub(super) fn check_completion(&self, detail: &Detail) -> Result<(), &'static str> {
        if matches!(
            detail,
            Detail::SpecSummary { .. } | Detail::AllClosed { .. }
        ) {
            return match &self.completion_verifier {
                Some(verify) => verify(detail),
                None => {
                    Err("completion verification is unavailable; orchestrator judgment required")
                }
            };
        }
        Ok(())
    }
    pub(super) fn check_fleet(&self, spec: Number) -> Result<(), &'static str> {
        self.check_stop()?;
        if self
            .fleet_authority
            .as_ref()
            .is_some_and(|allowed| !allowed(spec))
        {
            return Err("fleet takeover authority is unconfirmed");
        }
        Ok(())
    }
    pub(super) fn check_stop(&self) -> Result<(), &'static str> {
        if self.stop.load(std::sync::atomic::Ordering::SeqCst) {
            Err("tick stop requested")
        } else {
            Ok(())
        }
    }
    pub(super) fn check(&self, project: Option<&str>) -> Result<(), &'static str> {
        self.check_stop()?;
        if project != Some(self.project.as_str()) {
            return Err("configured project changed or unread");
        }
        Ok(())
    }
}
pub fn run_with_control(
    args: Args,
    context: Context<'_>,
    out: &mut dyn Write,
    control: &Control,
) -> Result<(), &'static str> {
    run_selected(args, context, out, Some(control))
}

pub fn run_with(args: Args, context: Context<'_>, out: &mut dyn Write) -> Result<(), &'static str> {
    run_selected(args, context, out, None)
}
fn run_selected(
    args: Args,
    context: Context<'_>,
    out: &mut dyn Write,
    control: Option<&Control>,
) -> Result<(), &'static str> {
    if let Some(control) = control {
        control.check_stop()?;
    }
    let deadline = crate::SystemClock.monotonic() + openwiz_core::limits::RUN_BUDGET;
    let inventory = graph::Inventory::read(context.github, deadline)?;
    if args.due && inventory.is_empty() {
        return Ok(());
    }
    run_observed(args, context, deadline, inventory, out, control, None)
}

fn run_observed(
    args: Args,
    context: Context<'_>,
    deadline: std::time::Instant,
    inventory: graph::Inventory,
    out: &mut dyn Write,
    control: Option<&Control>,
    expected: Option<&serde_json::Value>,
) -> Result<(), &'static str> {
    let Context {
        github: gh,
        room,
        state,
        orchestrator,
    } = context;
    let clock = crate::SystemClock;
    let mut world = graph::World::read(
        gh,
        if args.due { None } else { Some(room) },
        state,
        deadline,
        inventory,
    )?;
    if let Some(control) = control {
        control.check(world.project.as_deref())?;
    }
    world.orchestrator = orchestrator.map(str::to_owned);
    let deadline = world.deadline;
    let now = u64::try_from(clock.now().0).map_err(|_| "clock before epoch")?;
    // Dry-run previews do not include the independent recovery plan. Refuse
    // before recovery can claim a lock, settle local state or dispatch a write.
    if expected.is_some()
        && world.starts.iter().any(|record| {
            record.attempts().last().is_some_and(|attempt| {
                matches!(
                    attempt.outcome,
                    openwiz_core::fleet::starts::AttemptOutcome::Pending
                )
            })
        })
    {
        return Err("reviewed plan cannot authorize pending recovery");
    }
    let recovered = if !args.due && !args.dry_run {
        execute::recover(&mut world, gh, room, state, deadline, now, control)?
    } else {
        Vec::new()
    };
    let plan =
        tick::plan(&world.snapshot, &world.rules, now).map_err(|_| "fleet plan unavailable")?;
    if args.due {
        let mut candidates = plan
            .actions
            .iter()
            .map(|a| (a.spec, a.ticket))
            .collect::<BTreeSet<_>>();
        // Approval reports are candidates here, never merge authority: only
        // tick can verify the reviewer's own CloudRoom output. Only the latest
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

    let mut doc = serde_json::to_value(&plan).map_err(|_| "plan encoding failed")?;
    if let Some(expected) = expected {
        let mut comparable = doc.clone();
        // A preview necessarily used an earlier clock; only its type is a gate.
        comparable["planned_at"] = expected["planned_at"].clone();
        if comparable != *expected {
            return Err("reviewed plan differs from the current ordered plan");
        }
    }
    if !args.dry_run {
        doc["mode"] = "run".into();
        for (i, action) in plan.actions.iter().enumerate() {
            if let Some(control) = control {
                control.check(world.project.as_deref())?;
            }
            doc["actions"][i]["outcome"] =
                execute::perform(&mut world, gh, room, state, deadline, action, control);
        }
        if let Some(control) = control {
            control.check_stop()?;
        }
    }
    if args.json {
        doc["actions"]
            .as_array_mut()
            .ok_or("actions missing")?
            .splice(0..0, recovered);
        serde_json::to_writer_pretty(&mut *out, &doc).map_err(|_| "output failed")?;
        writeln!(out).map_err(|_| "output failed")?;
    } else {
        // Recovery ran before the plan was built, so its actions are not in
        // `plan`: report an unsuccessful one here, without executing it again.
        for reported in &recovered {
            write_diagnostic(reported, out)?;
        }
        for (i, action) in plan.actions.iter().enumerate() {
            let who = action.ticket.unwrap_or(action.spec);
            // A run whose action didn't end `done` is never silent: one line per
            // refused, failed or uncertain action, so a loop agent sees it.
            if !args.dry_run {
                let outcome = &doc["actions"][i]["outcome"];
                let state = outcome["state"].as_str().unwrap_or("");
                if state != "done" && state != "planned" {
                    let mut reported =
                        serde_json::to_value(action).map_err(|_| "encoding failed")?;
                    reported["outcome"] = outcome.clone();
                    write_diagnostic(&reported, out)?;
                    continue;
                }
            }
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

/// One line for an action, as its JSON object (with its outcome), whose
/// outcome is not `done`: refused, failed or uncertain. Nothing is written when
/// the action succeeded.
fn write_diagnostic(action: &serde_json::Value, out: &mut dyn Write) -> Result<(), &'static str> {
    let outcome = &action["outcome"];
    let state = outcome["state"].as_str().unwrap_or("");
    if state == "done" || state == "planned" {
        return Ok(());
    }
    let spec = action["spec"].as_u64().ok_or("spec missing")?;
    let who = action["ticket"]
        .as_u64()
        .map_or_else(|| spec.to_string(), |t| t.to_string());
    let rule = action["rule"].as_str().ok_or("rule missing")?;
    let reason = outcome["reason"].as_str().unwrap_or("");
    writeln!(out, "fleet #{spec}: #{who} {rule} {state}: {reason}").map_err(|_| "output failed")
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
